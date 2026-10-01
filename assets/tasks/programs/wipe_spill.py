# Wipe the table

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
            "next_step": 'Inspect and bind planar spill region, table support. Use a planar measured spill region. Sweep a padded zigzag raster with short Cartesian chords, maintaining contact through row transitions, then retract.',
        }

    # Measure regions selected from the current image.
    if phase == "discover":
        if inputs.get("task") != 'wipe_spill':
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

    if inputs.get("task") != 'wipe_spill':
        return inspect("Bind stage_inputs to this task and the current scene.")

    confirmed = set(inputs.get("confirmed", []))
    requirements = {'plan_raster': ['spill mask planar', 'spill bounds measured'],
     'prepare_wiper': ['spill mask planar', 'contact approach clear'],
     'wipe_step': ['wiper contact verified', 'next chord clear'],
     'retract_wiper': ['raster coverage inspected']}
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
        if phase == 'plan_raster':
            lo, hi = inputs["spill_lower_xyz"], inputs["spill_upper_xyz"]
            if not (0.015 < hi[0]-lo[0] < 0.55 and 0.015 < hi[1]-lo[1] < 0.55):
                return inspect("Resolve the planar spill bounds before contact.")
            margin = inputs["observed_sweep_margin_m"]
            pitch = inputs["observed_row_pitch_m"]
            chord = inputs["max_chord_m"]
            if not (0 <= margin <= 0.02 and 0 < pitch <= 0.025 and 0 < chord <= 0.025):
                return inspect("Resolve the tool footprint and short contact intervals.")
            x0,x1 = lo[0]-margin,hi[0]+margin
            y0,y1 = lo[1]-margin,hi[1]+margin
            intervals = (y1-y0)/pitch
            count = int(intervals)
            if count < intervals:
                count += 1
            rows = max(2, count+1)
            contact_z = inputs["observed_contact_center_z"]
            corners = [[x0,y0,contact_z]]
            for index in range(rows):
                y = y0 + (y1-y0)*index/(rows-1)
                corners.append([x1 if index%2 == 0 else x0,y,contact_z])
                if index+1 < rows:
                    next_y = y0 + (y1-y0)*(index+1)/(rows-1)
                    corners.append([corners[-1][0],next_y,contact_z])
            raster = []
            for start, end in zip(corners, corners[1:]):
                distance = sum((b-a)**2 for a,b in zip(start,end))**0.5
                parts = max(1, int(distance/chord) + 1)
                for step in range(1, parts+1):
                    raster.append([a+(b-a)*step/parts for a,b in zip(start,end)])
            state = dict(saved)
            state["wipe_plan"] = {"centers":raster, "start":corners[0], "max_chord_m":chord}
            state["wipe_index"] = 0
            return {"status":"need_observation", "execution_state":state,
                    "raster_centers_xyz":raster,
                    "start_center_xyz":corners[0], "max_chord_m":chord,
                    "next_step":"Bind calibrated contact/tool poses and approach before sweeping."}

        if phase == 'prepare_wiper':
            hover, contact = inputs["hover_pose"], inputs["contact_pose"]
            checked_motion(lambda: api.goto_pose(arm, hover["position_xyz"], hover["orientation_xyzw"]))
            checked_motion(lambda: api.gripper_goto(arm, 0.0))
            moved = checked_motion(lambda: api.goto_pose(
                arm, contact["position_xyz"], contact["orientation_xyzw"]))
            return inspect("Inspect tool contact before starting the first sweep.", moved)

        if phase == 'wipe_step':
            plan = saved.get("wipe_plan") or {}
            index = saved.get("wipe_index", 0)
            centers = plan.get("centers") or []
            if not (0 <= index < len(centers)):
                return inspect("Resolve the next unexecuted raster segment.")
            current, orientation = api.get_end_effector_pose(arm)
            pose = api.grasp_center_to_tool0_pose(centers[index], orientation_xyzw=orientation)
            if pose.get("status") != "ok" or not valid_pose(pose):
                return inspect("Resolve the next contact pose.", pose)
            target = pose["target_position_xyz"]
            distance = sum((b-a)**2 for a,b in zip(current,target))**0.5
            if (distance > plan["max_chord_m"] + 0.000001
                    or abs(target[2]-current[2]) > 0.000001):
                return inspect("Re-establish the planned surface contact before the next short segment.")
            moved = checked_motion(lambda: api.goto_pose(
                arm, target, pose["orientation_xyzw"], z_approach=0.0))
            saved["wipe_index"] = index + 1
            return inspect("Inspect contact and spill change before the next chord.", moved)

        if phase == 'retract_wiper':
            plan = saved.get("wipe_plan") or {}
            if not plan.get("centers") or saved.get("wipe_index", 0) != len(plan["centers"]):
                return inspect("Complete the planned sweep and row transitions before retracting.")
            pose = inputs["retract_pose"]
            moved = checked_motion(lambda: api.goto_pose(
                arm, pose["position_xyz"], pose["orientation_xyzw"]))
            checked_motion(lambda: api.gripper_goto(arm, inputs["open_width_m"]))
            return inspect("Inspect the resulting tabletop surface.", moved)
    except (KeyError, TypeError, ValueError, RuntimeError) as error:
        return inspect("Inspect the current scene before continuing.",
                       {"interrupted_stage": phase, "detail": str(error)})
