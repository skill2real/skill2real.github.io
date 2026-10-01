# Lift with both arms

def main(api, stage_inputs):
    """Run one Proposer decision stage with episode-local execution state."""
    previous = api.get_previous_proposer_state() or {}
    saved = previous.get("execution_state") or {}
    inputs = stage_inputs
    phase = inputs.get("phase", "observe")
    motion_epoch = saved.get("motion_epoch", 0)

    def inspect(next_action, results=None):
        views = {"scene": api.get_scene_image(), "topdown": api.get_topdown_image()}
        for active_arm in inputs.get("active_arms", ["left", "right"]):
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
            "next_step": 'Inspect and bind green outer handle crossbar, blue outer handle crossbar. Grasp both outer crossbars, seat both contacts along their observed axis, and lift both hands together. Keep the pot level and inspect both contacts after each lift increment.',
        }

    # Measure regions selected from the current image.
    if phase == "discover":
        if inputs.get("task") != 'two_arm_pot_lift':
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

    if inputs.get("task") != 'two_arm_pot_lift':
        return inspect("Bind stage_inputs to this task and the current scene.")

    confirmed = set(inputs.get("confirmed", []))
    requirements = {'capture_handles': ['both crossbars bound', 'paired approaches clear'],
     'seat_handles': ['both handles retained', 'balanced seating poses bound'],
     'paired_lift': ['both handles retained', 'pot level verified']}
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
        if phase == 'capture_handles':
            left = api.compile_pose("grasp", inputs["left_grasp_request"])
            right = api.compile_pose("grasp", inputs["right_grasp_request"])
            if left.get("status") != "ok" or right.get("status") != "ok":
                return inspect("Resolve both grasp poses before moving either arm.", [left,right])
            if not valid_pose(left) or not valid_pose(right):
                return inspect("Resolve both contact poses.")
            approaches = []
            for pose, request in [(left, inputs["left_grasp_request"]),
                                  (right, inputs["right_grasp_request"])]:
                axis = request["approach_axis_world"]
                norm = sum(v*v for v in axis) ** 0.5
                distance = inputs["approach_distance_m"]
                if len(axis) != 3 or norm < 0.000001 or not (0 < distance <= 0.2):
                    return inspect("Resolve both approach corridors.")
                approaches.append([p-distance*a/norm for p,a in zip(pose["target_position_xyz"],axis)])
            checked_motion(lambda: api.gripper_goto("left", inputs["left_open_width_m"]))
            checked_motion(lambda: api.gripper_goto("right", inputs["right_open_width_m"]))
            for left_xyz, right_xyz in [(approaches[0], approaches[1]),
                                        (left["target_position_xyz"], right["target_position_xyz"])]:
                checked_motion(lambda: api.goto_pose_both(
                    left_xyz, left["orientation_xyzw"], right_xyz, right["orientation_xyzw"], z_approach=0.0))
            checked_motion(lambda: api.gripper_goto("left", 0.0))
            checked_motion(lambda: api.gripper_goto("right", 0.0))
            return inspect("Inspect both captured crossbars before balanced seating.")

        if phase == 'seat_handles':
            request = inputs["paired_seating_request"]
            if set(request) - {"position0", "quaternion_xyzw0", "position1", "quaternion_xyzw1", "z_approach"}:
                return inspect("Resolve the documented paired poses.")
            for index in (0, 1):
                if not valid_pose({"target_position_xyz": request.get("position"+str(index)),
                                   "orientation_xyzw": request.get("quaternion_xyzw"+str(index))}):
                    return inspect("Resolve both paired poses before motion.")
            result = checked_motion(lambda: api.goto_pose_both(**request))
            return inspect("Inspect both contacts and pot level before lifting.", result)

        if phase == 'paired_lift':
            if not (0 < inputs["lift_offset_m"] <= inputs["observed_lift_clearance_m"]):
                return inspect("Choose a short lift within the observed paired clearance.")
            left_xyz, left_q = api.get_end_effector_pose("left")
            right_xyz, right_q = api.get_end_effector_pose("right")
            for xyz, q in [(left_xyz,left_q), (right_xyz,right_q)]:
                if not valid_pose({"target_position_xyz":xyz, "orientation_xyzw":q}):
                    return inspect("Resolve both current tool poses before lifting.")
            rise = inputs["lift_offset_m"]
            left_next = [left_xyz[0], left_xyz[1], left_xyz[2] + rise]
            right_next = [right_xyz[0], right_xyz[1], right_xyz[2] + rise]
            result = checked_motion(lambda: api.goto_pose_both(
                left_next, left_q, right_next, right_q, z_approach=0.0))
            return inspect("Inspect both retained contacts and pot level. Keep both grippers closed.", result)
    except (KeyError, TypeError, ValueError, RuntimeError) as error:
        return inspect("Inspect the current scene before continuing.",
                       {"interrupted_stage": phase, "detail": str(error)})
