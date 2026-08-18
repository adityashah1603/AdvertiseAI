1. Hard Disqualifiers - none violate all checked individually
    - nothing but the agent moves work out of the box, no tenant/task identity in sandbox, agent never on laptop, agent never a backend subprocess, no work exists only on a box, no hardcoded ordering - can submit any comapny(new or already existing) in any order. 
    - Note: used a test script to read the checksum of file we wrote in, this was only for diagnostics and debugging and doesnt get called when the process is running

2. skills.md's 7 invariants:
    - Plate first - one plate live html on top, nothing else
    - one plate per canvas size - never reframe one plate onto different ratio
    - Every word is live html
    - Logo is never stretched or skewed
    - Design.md wins over tokens, manifests, inspiration
    - inspiration are reference only - never source of color, type or copy
    - never publish -generation agent has no adstream credential

3. Brief's core idea:
    - three data layers kept seperate everywhere - global(skill/tooling, same every run), tenant (the brand, fetched fresh every run, never cached), job (the request itself). A rebrand needs zero rebuild. 

4. Storage/hydration/Resume
    - Hydration functions are pure — same ids in, same files out, always.
    - Resume = replaying that same function, not a separate mechanism.
    - The agent saves its own work from inside the box; the orchestrator only ever reads back from Storage, never trusts the agent's word alone.

5. Built vs stubbed: 
    - all 4 parts done(generate, engine, feedback, deploy)
    - not built deliberately : brand kit versioning, brand conformance grader, edit routing classifier, custom scheduler, credential perm system, latency optimization

6. The four routed policy questions:
    - Brand changes mid-task → always fetch fresh, never freeze. Surface the change, don't block on it.
    - Stale pinned comment → open → resolved → orphaned. No auto-remapping, ever.
    - Concurrency cap → independent pools for generate/edit vs. deploy, enforced in Postgres, excess just queues.
    - Credential blast radius → generation gets OpenAI+Anthropic, deploy gets Anthropic+Adstream — never overlapping, neither ever touches the database directly.

7. Future Work: 
    - Auto reconcile run where orchestrator dies but run succeeds
    - for retry - avoid rebilling, could save a few cents
    - Deploy not idempotent - currently frontend doesnt check if the verified deploy already exists before calling other one - could lead to two same campaigns under new name (duplicate)

8. Least sure of:
    - "surface, dont block" on brand change is good for real operator
    - orphaning stale comment loses real feedback
    - FIFO would hold up at scale
    - Every render got the same scrutiny as the documented second pass
    
