"""PEICO benchmark package.

Two layers live here:

- the **data domain + physics** — ``build_reference``, ``generate``, and the
  deterministic ``rating`` engine — which produce and price the world; and
- the **harness** (``peico.harness``) — world provisioning, the environment
  service, the customer simulator, grading, and the runner — which evaluates an
  agent implementation against a task.

The harness depends on the rating engine (one source of physics, per design
principle 8); nothing in the data/physics layer imports the harness.
"""
