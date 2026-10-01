# Pudding & drawer

def main(api, stage_inputs):
    """Run one Proposer decision stage with episode-local execution state."""
    previous = api.get_previous_proposer_state() or {}
    saved = previous.get("execution_state") or {}
    inputs = stage_inputs
    phase = inputs.get("phase", "observe")
    motion_epoch = saved.get("motion_epoch", 0)

    def inspect(next_action, results=None):
        views = {"scene": api.get_scene_image(), "topdown": api.get_topdown_image()}
        for active_arm in inputs.get("active_arms", [inputs.get("arm")]):
            if active_arm in ("left", "right"):
                views[active_arm + "_wrist"] = api.get_wrist_view(active_arm)
        state = dict(saved)
        state["motion_epoch"] = motion_epoch
        state["retention_observation"] = {"motion_epoch": motion_epoch, "views": views}
        if motion_epoch != saved.get("motion_epoch", 0):
            state.pop("depth_evidence", None)
        return {
            "status": "need_observation",
            "request_views": ["topdown"],
            "execution_state": state,
            "outcome_evidence": {"views": views, "results": results},
            "next_step": next_action,
        }

    def checked_motion(command):
        nonlocal motion_epoch
        motion_epoch += 1
        result = command()
        if (not isinstance(result, dict) or result.get("status") != "ok"
                or result.get("execution_ok") is not True):
            raise RuntimeError({"motion_not_confirmed": result})
        return result

    def valid_pose(pose):
        if not isinstance(pose, dict):
            return False
        xyz, q = pose.get("target_position_xyz"), pose.get("orientation_xyzw")
        return (isinstance(xyz, (list, tuple)) and len(xyz) == 3
                and isinstance(q, (list, tuple)) and len(q) == 4
                and all(isinstance(v, (int, float)) and abs(v) < float("inf")
                        for v in [*xyz, *q]) and abs(sum(v*v for v in q) - 1.0) <= 0.001)

    if phase == "observe":
        return {
            "status": "need_observation",
            "outcome_evidence": {
                "scene": api.get_scene_image(),
                "topdown": api.get_topdown_image(),
                "previous": previous,
            },
            "next_step": 'Inspect and bind chocolate pudding, open top drawer interior, drawer handle. Place the pudding and inspect its released position before closing the drawer. Rebind the handle after the placement changes the scene.',
        }

    # Measure regions selected from the current image.
    if phase == "discover":
        if inputs.get("task") != 'pudding_drawer':
            return inspect("Bind the task before selecting a source.")
        if previous.get("held_object_state") or saved.get("held_state_unresolved"):
            return inspect("Resolve the active object's retention or release before selecting another source.")
        if inputs.get("camera_clear") is not True or inputs.get("evidence_epoch") != motion_epoch:
            return inspect("Inspect a clear tabletop view before source discovery.")
        return api.get_topdown_object_candidates()
    if phase == "observe_retention":
        return inspect("Inspect contact in the wrist view and object motion relative to its support. Keep unresolved contact unconfirmed.")
    if phase in ("stereo", "depth"):
        stereo = api.get_topdown_stereo_view(refresh_rgbd=True)
        if not isinstance(stereo, dict) or stereo.get("status") != "ok":
            return inspect("Obtain a calibrated stereo observation.", stereo)
        left, right = stereo.get("left") or {}, stereo.get("right") or {}
        if not left.get("image_path") or not right.get("image_path"):
            return inspect("Resolve both calibrated image paths.", stereo)
        calibration = {}
        for side, camera in [("left", left), ("right", right)]:
            for field in ("intrinsics_path", "extrinsics_path"):
                if camera.get(field):
                    calibration[side + "_" + field] = camera[field]
        depth = api.get_foundation_stereo_depth(
            left["image_path"], right["image_path"], **calibration)
        if (not isinstance(depth, dict) or depth.get("status") != "ok"
                or not depth.get("observation_ref") or not depth.get("depth_ref")):
            return inspect("Resolve depth for the displayed stereo pair.", depth)
        state = dict(saved)
        state["depth_evidence"] = {"left_image_path": left["image_path"],
                                   "right_image_path": right["image_path"],
                                   "motion_epoch": motion_epoch, "depth": depth}
        return {"status": "need_observation", "execution_state": state,
                "outcome_evidence": {"topdown": left["image_path"], "depth": depth},
                "next_step": "Select the target and isolated regions on this image. Use its matching depth and calibration; leave hidden surfaces unresolved."}
    if phase == "segment":
        evidence = saved.get("depth_evidence") or {}
        if (evidence.get("motion_epoch") != motion_epoch
                or inputs.get("image_path") != evidence.get("left_image_path")):
            return inspect("Select regions on the image bound to the current depth.")
        boxes = inputs.get("named_boxes")
        if not isinstance(boxes, dict) or not boxes:
            return inspect("Select named image boxes for the current observation.")
        masks = {name: api.get_sam_mask_from_box(evidence["left_image_path"], box)
                 for name, box in boxes.items()}
        state = dict(saved)
        state["region_masks"] = {"image_path": evidence["left_image_path"],
                                  "motion_epoch": motion_epoch, "masks": masks}
        return {"status": "need_observation", "execution_state": state,
                "outcome_evidence": masks,
                "next_step": "Inspect each mask for isolated object coverage before measuring it."}
    if phase == "measure":
        evidence = saved.get("depth_evidence") or {}
        regions = saved.get("region_masks") or {}
        depth = evidence.get("depth") or {}
        names = inputs.get("isolated_regions") or []
        if (not names or evidence.get("motion_epoch") != motion_epoch
                or regions.get("motion_epoch") != motion_epoch
                or regions.get("image_path") != evidence.get("left_image_path")
                or not all(depth.get(key) for key in ("depth_path", "rectified_intrinsics_path", "rectification_summary_path"))):
            return inspect("Resolve isolated masks and matching calibrated depth before measuring.")
        selected = {name: (regions.get("masks") or {}).get(name) or {} for name in names}
        if any(mask.get("status") != "ok" or not mask.get("mask_path") for mask in selected.values()):
            return inspect("Resolve each selected object mask.", selected)
        geometry = {name: api.measure_visible_geometry(
                        mask["mask_path"], depth["depth_path"],
                        depth["rectified_intrinsics_path"],
                        rectification_summary_path=depth["rectification_summary_path"])
                    for name, mask in selected.items()}
        state = dict(saved)
        state["visible_geometry"] = geometry
        return {"status": "need_observation", "execution_state": state,
                "outcome_evidence": geometry,
                "next_step": "Use the visible measurements and image evidence to select contact and placement geometry."}

    if inputs.get("task") != 'pudding_drawer':
        return inspect("Bind stage_inputs to this task and the current scene.")

    confirmed = set(inputs.get("confirmed", []))
    requirements = {'object_1_grasp': ['chocolate pudding bound', 'approach clear'],
     'object_1_lift': ['chocolate pudding retained', 'lift corridor clear'],
     'object_1_carry': ['chocolate pudding retained',
                        'open top drawer bound',
                        'transport corridor clear'],
     'object_1_lower': ['chocolate pudding retained',
                        'open top drawer bound',
                        'release alignment verified'],
     'object_1_release': ['chocolate pudding supported at open top drawer'],
     'object_1_clear': ['chocolate pudding placed at open top drawer',
                        'release separation verified'],
     'push_chain': ['contact face bound',
                    'push corridor clear',
                    'chocolate pudding placed at open top drawer']}
    if phase not in requirements:
        return inspect("Choose a stage from this task's program.")
    if requirements[phase] and inputs.get("evidence_epoch") != motion_epoch:
        return inspect("Refresh the action conditions from observations after the latest motion.")
    missing = [item for item in requirements[phase] if item not in confirmed]
    if missing:
        return inspect("Inspect before moving: " + "; ".join(missing))

    arm = inputs.get("arm")
    if any("retained" in item for item in requirements[phase]):
        observation = saved.get("retention_observation") or {}
        reviews = inputs.get("retention_reviews") or {}
        active_arms = ["left", "right"] if "both handles retained" in requirements[phase] else [arm]
        for active_arm in active_arms:
            review = reviews.get(active_arm) or {}
            wrist = (observation.get("views") or {}).get(str(active_arm) + "_wrist") or {}
            if (observation.get("motion_epoch") != motion_epoch
                    or review.get("motion_epoch") != motion_epoch
                    or not wrist.get("image_path")
                    or review.get("image_path") != wrist["image_path"]
                    or review.get("contact_supported") is not True):
                return inspect("Confirm the active contact from the fresh wrist image before continuing.")
            if phase.endswith(("_carry", "_lower")) and review.get("lift_supported") is not True:
                return inspect("Confirm that the object moved with the gripper and cleared its support before transport.")
    try:
        if phase == 'object_1_grasp':
            grasp = api.compile_pose("grasp", inputs["grasp_request"])
            if grasp.get("status") != "ok" or not valid_pose(grasp):
                return inspect("Resolve grasp geometry before motion.", grasp)
            q = grasp["orientation_xyzw"]
            axis = inputs["grasp_request"]["approach_axis_world"]
            norm = sum(v*v for v in axis) ** 0.5
            distance = inputs["approach_distance_m"]
            if len(axis) != 3 or norm < 0.000001 or not (0 < distance <= 0.2):
                return inspect("Resolve approach direction and clearance.")
            pregrasp = [p - distance*a/norm
                        for p, a in zip(grasp["target_position_xyz"], axis)]
            opening = inputs["open_width_m"]
            commands = [
                lambda: api.gripper_goto(arm, opening),
                lambda: api.goto_pose(arm, pregrasp, q, z_approach=0.0),
                lambda: api.goto_pose(arm, grasp["target_position_xyz"], q, z_approach=0.0),
                lambda: api.gripper_goto(arm, 0.0),
            ]
            receipts = [checked_motion(command) for command in commands]
            return inspect("Check the selected contact and retention before continuing.", receipts)

        if phase == 'object_1_lift':
            pose = api.grasp_center_to_tool0_pose(
                inputs["next_grasp_center_xyz"],
                orientation_xyzw=inputs["orientation_xyzw"])
            if pose.get("status") != "ok":
                return inspect("Resolve the next lift pose.", pose)
            moved = checked_motion(lambda: api.goto_pose(
                arm, pose["target_position_xyz"], pose["orientation_xyzw"]))
            return inspect("Check retention and clearance before the next segment.", moved)

        if phase == 'object_1_carry':
            request = dict(inputs["place_request"])
            allowed = {"observation_ref", "depth_ref", "target_pixel_uv", "pixel_space",
                       "table_z_world", "held_object_state", "relation", "arm"}
            if set(request) - allowed:
                return inspect("Use the documented placement inputs and runtime carry geometry.")
            evidence = saved.get("depth_evidence") or {}
            depth = evidence.get("depth") or {}
            if (evidence.get("motion_epoch") != motion_epoch
                    or request.get("observation_ref") != depth.get("observation_ref")
                    or request.get("depth_ref") != depth.get("depth_ref")):
                return inspect("Bind the destination pixel to the current stereo image and its depth.")
            request["held_object_state"] = previous.get("held_object_state")
            request["table_z_world"] = previous.get("table_z_world")
            required = ["observation_ref", "depth_ref", "target_pixel_uv", "pixel_space",
                        "held_object_state", "table_z_world", "relation"]
            if any(request.get(key) is None for key in required):
                return inspect("Bind current target depth and runtime carry geometry.")
            place = api.compile_pose("place", request)
            if place.get("status") != "ok":
                return inspect("Resolve target support and clearance.", place)
            pose = place.get("carry_tool0_pose")
            if not valid_pose(pose):
                return inspect("Resolve the compiled placement pose.", place)
            saved["placement_retreat_pose"] = place.get("retreat_pose")
            moved = checked_motion(lambda: api.goto_pose(
                arm, pose["target_position_xyz"], pose["orientation_xyzw"], z_approach=0.0))
            return inspect("Inspect the carried object and destination before continuing.", moved)

        if phase == 'object_1_lower':
            request = dict(inputs["place_request"])
            allowed = {"observation_ref", "depth_ref", "target_pixel_uv", "pixel_space",
                       "table_z_world", "held_object_state", "relation", "arm"}
            if set(request) - allowed:
                return inspect("Use the documented placement inputs and runtime carry geometry.")
            evidence = saved.get("depth_evidence") or {}
            depth = evidence.get("depth") or {}
            if (evidence.get("motion_epoch") != motion_epoch
                    or request.get("observation_ref") != depth.get("observation_ref")
                    or request.get("depth_ref") != depth.get("depth_ref")):
                return inspect("Bind the destination pixel to the current stereo image and its depth.")
            request["held_object_state"] = previous.get("held_object_state")
            request["table_z_world"] = previous.get("table_z_world")
            required = ["observation_ref", "depth_ref", "target_pixel_uv", "pixel_space",
                        "held_object_state", "table_z_world", "relation"]
            if any(request.get(key) is None for key in required):
                return inspect("Bind current target depth and runtime carry geometry.")
            place = api.compile_pose("place", request)
            if place.get("status") != "ok":
                return inspect("Resolve target support and clearance.", place)
            pose = place.get("release_tool0_pose")
            if not valid_pose(pose):
                return inspect("Resolve the compiled placement pose.", place)
            saved["placement_retreat_pose"] = place.get("retreat_pose")
            moved = checked_motion(lambda: api.goto_pose(
                arm, pose["target_position_xyz"], pose["orientation_xyzw"], z_approach=0.0))
            return inspect("Inspect the carried object and destination before continuing.", moved)

        if phase == 'object_1_release':
            opened = checked_motion(lambda: api.gripper_goto(arm, inputs["open_width_m"]))
            return inspect("Inspect release separation and the placed relation before any next objective.", opened)

        if phase == 'object_1_clear':
            parked = checked_motion(lambda: api.gohome(arm))
            return inspect("Inspect the placed relation and bind the next objective.", parked)

        if phase == 'push_chain':
            direction = inputs["inward_axis_world"]
            norm = sum(v*v for v in direction) ** 0.5
            distance = inputs["push_distance_m"]
            high = inputs["free_space_clearance_m"]
            near = inputs["precontact_clearance_m"]
            retreat = inputs["retreat_height_m"]
            if (len(direction) != 3 or norm < 0.000001
                    or abs(direction[2]) > 0.000001 or not (0 < distance <= 0.25)
                    or not (0 < near < high <= 0.2) or not (near < retreat <= 0.2)):
                return inspect("Resolve the push direction, distance and vertical clearances.")
            request = dict(inputs["push_grasp_request"])
            request["orientation_role"] = "closed_finger_pusher"
            request["closing_axis_world"] = direction
            compiled = api.compile_pose("grasp", request)
            if compiled.get("status") != "ok" or not valid_pose(compiled):
                return inspect("Resolve the pusher orientation from the selected visual anchor.", compiled)
            pose = api.grasp_center_to_tool0_pose(
                inputs["contact_center_xyz"], orientation_xyzw=compiled["orientation_xyzw"])
            if pose.get("status") != "ok" or not valid_pose(pose):
                return inspect("Resolve the selected contact pose.", pose)
            contact, q = pose["target_position_xyz"], pose["orientation_xyzw"]
            checked_motion(lambda: api.gripper_goto(
                arm, 0.0, motion_intent="prepare_closed_finger_pusher"))
            for clearance in [high, near]:
                above = [contact[0], contact[1], contact[2] + clearance]
                checked_motion(lambda: api.goto_pose(
                    arm, above, q, z_approach=0.0,
                    motion_intent="closed_finger_push_precontact"))
            receipts, interrupted = [], None
            try:
                receipts.append(checked_motion(lambda: api.goto_pose(
                    arm, contact, q, z_approach=0.0,
                    motion_intent="closed_finger_push_contact_approach")))
                count = max(1, int(distance / 0.02) + 1)
                for index in range(1, count + 1):
                    point = [c + distance*index/count*d/norm
                             for c,d in zip(contact, direction)]
                    receipts.append(checked_motion(lambda: api.goto_pose(
                        arm, point, q, z_approach=0.0,
                        motion_intent="closed_finger_push_segment")))
            except RuntimeError as error:
                interrupted = str(error)
            current_xyz, current_q = api.get_end_effector_pose(arm)
            if not valid_pose({"target_position_xyz": current_xyz, "orientation_xyzw": current_q}):
                return inspect("Resolve the actual tool pose before retreating.", receipts)
            above = [current_xyz[0], current_xyz[1], current_xyz[2] + retreat]
            checked_motion(lambda: api.goto_pose(
                arm, above, current_q, z_approach=0.0,
                motion_intent="closed_finger_push_vertical_retreat"))
            checked_motion(lambda: api.gripper_goto(
                arm, inputs["open_width_m"], motion_intent="release_pusher_after_retreat"))
            return inspect("Inspect displacement and rebind the object before another contact episode.",
                           {"motions": receipts, "interruption": interrupted})
    except (KeyError, TypeError, ValueError, RuntimeError) as error:
        return inspect("Inspect the current scene before continuing.",
                       {"interrupted_stage": phase, "detail": str(error)})
