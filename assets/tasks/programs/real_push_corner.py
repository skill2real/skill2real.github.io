# Push into a corner

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
            "next_step": 'Inspect and bind cube, container corner, free push corridor. Choose the contacted cube face and the observed direction toward the corner. Use short pushes and inspect displacement before continuing.',
        }

    # Measure regions selected from the current image.
    if phase == "discover":
        if inputs.get("task") != 'real_push_corner':
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

    if inputs.get("task") != 'real_push_corner':
        return inspect("Bind stage_inputs to this task and the current scene.")

    confirmed = set(inputs.get("confirmed", []))
    requirements = {'push_chain': ['contact face bound', 'push corridor clear']}
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
