# Skill memory guides program generation

Brain and Cerebellum skills are textual memories read by the Proposer.
They are not functions imported from a Python skill package.

The Brain provides task-level guidance. The Cerebellum provides local
manipulation knowledge. The Proposer reads both memories together with the
goal, current public observations, API results, and API documentation, then
writes the next executable program.

The paper describes a skill as natural-language guidance, an API-level code
template, and a lightweight state description. Code inside a skill document
is context for program generation; it is not an additional callable API.

## An actual stored-text example

This excerpt comes from an archived simulation Brain document, brain_skill.md,
for the can-into-tray task. It illustrates the stored format, not a shared
checkpoint assignment for every video in this gallery.

“Decision change: bind the actionable destination region to the coherent dense
raised interior band inside the parent and reject the lower gap returns; stop
as unresolved if the inset is not parent-consistent or no coherent band exists.”

Context: the stored rule distinguishes the raised interior of a slatted tray
from a lower surface visible through its gaps.

## During deployment

The Proposer reads the frozen skill text and generates API calls for the
current scene. Observations, object bindings, generated programs, and episode
state can change. The learned skill memories remain fixed.

References: paper Method, Hierarchical Skill Training; appendix Skill Invocation
and the PVG Evidence Boundary; archived can-into-tray brain_skill.md,
destination entry. This is a shared method reference, not an execution log.
