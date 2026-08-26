from kokoro import KPipeline
from IPython.display import display, Audio
import soundfile as sf
import torch

pipeline = KPipeline(lang_code="a")
text = """
ARP Eval Operationalization
Progress, Learnings, and Nuances from the Alpha Run  |  For: Engineering Director, VP Engineering, TPM & Product Directors
Context
The ARP (Agent Readiness Platform) Eval team is running an Alpha with IPS, App Fabric (Mobile, Web & Service), Service Builder, GenOS, and other capability teams. The goal: identify each team's core use cases, run them through the ARP Eval framework, and surface agent-readiness frictions with detailed reports and Jira tracking. This one-pager shares what we hypothesized, what we've learned, and the technical, operational, process, mindset, and skill challenges surfacing as we operationalize.
Hypothesis → Learning


Hypothesis
Learning
H1
Running the ARP Eval framework against each capability team's core use cases would surface concrete, defensible agent-readiness frictions that teams could self-serve accept and act on from the report alone.
Partially validated. The eval mechanics work well: we've run evals across multiple teams' use cases and produced detailed friction reports with Jira assignment and tracking. However, live calls with new capabilities have become the de facto operating practice despite an async workflow built into the UI, as every friction still routes through a live review call with ARP Eval engineers before teams will accept it. Often, frictions found are already known or understandable to SMEs, but questions about the scoring rubric and ARP itself consume more time than the frictions discussion — though once educated on the process, new frictions are addressed quicker. Crucially, use case alignment (prerequisites, spec, and acceptance criteria) is the true long pole; once that alignment is complete, execution and assessment are efficient and effectively fire-and-forget.
H2
Documentation and FAQs would let capability teams understand the ARP scoring mechanism well enough that review calls could focus on disputing specific frictions, not on learning the framework.
Not yet validated. Docs and FAQs are largely unread going into these calls. Review calls are functioning as first-touch education rather than dispute resolution, regardless of what's already published. However, we see significantly better engagement and outcomes when a champion from the capability team provides advocacy beforehand, coming prepared having read through the documentation and FAQs.
H3
High existing adoption of coding assistants (e.g., Claude) across Intuit engineering implies a working baseline understanding of agentic development that ARP Eval could build on.
Disproven so far. Tool adoption and conceptual understanding are turning out to be separate things. Most engineers can prompt a coding assistant but don't yet have a mental model for agent architecture, modes, or how to plan/execute agent-assisted work efficiently — which is exactly the gap ARP Eval is trying to measure. Existing engagements are typically at the L2–L3 band of builder proficiency in the Agent-Driven Development rubric, while ARP introduces advanced concepts for the L3–L4 bands that are less familiar to capability teams.

Key Observation: Friction Review Calls Are Becoming “ARP University”
When receiving teams review logged frictions before accepting them, the calls consistently drift from ticket disposition into open-ended tutoring. Capability team attendance is broad and informal, documentation is skipped, and the ARP Eval engineers — who are meaningfully ahead of the org on how models plan and execute, and how to run agent tasks efficiently — end up cast as trainers rather than reviewers. This dilutes the calls' purpose (accept/dispute assigned frictions) into a recurring, unscoped agentic-development lesson, at the cost of ARP Eval engineering capacity.
Emerging Gap: No Shared Definition of “Agent Ready”
A more fundamental issue sits underneath the mindset gap: there is no consistent definition across the org of what “agent ready” actually means. Leadership discussions (e.g., 3x forums) are anchored on full autonomy, while capability teams often assume some human-in-the-loop prerequisites are acceptable. Absent a clear charter, ARP Eval becomes the de facto arbiter and educator on this question rather than capability owners receiving direction from leadership. Competing goals compound this — for example, LG06's target of 80% of JTBDs being agent-ready doesn't resolve the gap: the remaining 20% of human-blocking tasks still prevents full autonomy, so teams aren't actually incentivized to close it.
Challenges by Category
Technical:  Scoring mechanism is not yet self-explanatory from the artifacts alone; teams can't independently reconcile a friction against their own use case without a walkthrough. To understand their score and readiness, capability teams must first build a mental model of the end-to-end ARP flow — tracing Use Case → Use Case Step → Capability Unit-of-Work → observed AssessmentRun step → friction → capability deduped friction → score/readiness — as well as the underlying scoring rubric.
Operational:  Review call attendance is uncapped and informal, with no agenda discipline — this scales ARP Eval engineering time linearly with every new team we onboard, unsustainable at Beta/GA volumes.
Process:  There is no tiered engagement model. Every question, from a basic “what does this mode mean” to a genuine scoring dispute, lands on the same call with the same senior ARP engineers — there's no triage or self-serve path in between.
Mindset:  Expectation mismatch: ARP Eval expects teams to bring critical use cases, trust the mechanism, and act on frictions as delivered. Capability teams are instead treating frictions as negotiable starting points and the review call as the venue to relitigate the framework itself.
Skill:  Org-wide gap between tool adoption and agentic fluency — strong Claude usage does not translate into understanding agent architecture, modes, or efficient agent-assisted planning/execution. This gap is precisely what makes ARP Eval engineers indispensable, but also what's overloading them.
What We're Asking For
Set a clear, consistent charter for what “agent ready” and “autonomy” mean across the org, so capability owners get direction from leadership rather than from ARP Eval, and reconcile competing goals (e.g., LG06's 80%-of-JTBD metric) so they actually incentivize teams to close the full-autonomy gap rather than stopping short of it.
Give ARP Eval a defined period (e.g., a quarter) to harden the platform end-to-end — automating reruns, and building out reporting and tracking workflows — before expanding adoption to additional teams. Impact will show through platform scale and reliability, not through prematurely growing the number of onboarded teams.
Sponsor a short, standalone “Agent Readiness Fundamentals” enablement track (owned outside ARP Eval, e.g., L&D or a capability-team champion) so review calls stop absorbing that need.
Set and communicate attendee/agenda norms for friction review calls so they function as acceptance meetings, not open forums, and track ARP Eval engineering time spent on these calls as an explicit cost metric — it's currently invisible but is the main scaling risk as we move from Alpha to broader rollout.
Continue the recent practice of splitting sessions by audience — champions/scorecard owners, new-team onboarding, and friction review — which has already improved engagement and outcomes during Alpha.
"""
generator = pipeline(text, voice="af_heart")
for i, (gs, ps, audio) in enumerate(generator):
    print(i, gs, ps)
    display(Audio(data=audio, rate=24000, autoplay=i == 0))
    sf.write(f"{i}.wav", audio, 24000)
