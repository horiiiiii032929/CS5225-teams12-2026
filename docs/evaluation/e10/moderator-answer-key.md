# Moderator-only E10 answer key

Synthetic study stimuli; no participant observations or real-data acceptance.
Do not show this file, the fixture JSON or the other condition to participants.

- Fixture SHA-256: `9745ff6b9634cba4ff3397ad5a2e543c55e78a07738b2a37f5eb2f991facd99d`
- Ranker SHA-256: `4c08d8fe92420436839e60f54e60cd3a64f09b874d22e78a82fe68b10c113bf4`
- Reproduce: `uv run --package flatsplit-api python tools/evaluation/prepare_e10.py --check`.

## Scenario X

- Balanced order: Amber, Birch, Cedar.
- Fairer commutes order: Birch, Cedar, Amber.
- Amber's longest commute: **Sam, 40 min**; gap 20 min.
- Birch: longest 31 min; gap 2 min; S$400/person/month more than Amber.
- Card A: a member cannot be identified from the average alone. Record `not_observable` for member-identification accuracy; separately record whether the participant recognises the missing information. A guess is not evidence of understanding.
- Card B: naming the member above and identifying the smaller Birch gap supports fairness understanding. Birch becomes first because the priority weights commute gap more heavily; every town remains feasible. Accept equivalent plain-language explanations, not only numeric recall.
- A preference for Amber, Birch or Cedar is not right/wrong. Code whether the explanation uses the available rent/commute trade-off; do not reward agreement with the ranking.

## Scenario Y

- Balanced order: Amber, Birch, Cedar.
- Fairer commutes order: Birch, Cedar, Amber.
- Amber's longest commute: **Dee, 42 min**; gap 20 min.
- Birch: longest 33 min; gap 2 min; S$400/person/month more than Amber.
- Card A: a member cannot be identified from the average alone. Record `not_observable` for member-identification accuracy; separately record whether the participant recognises the missing information. A guess is not evidence of understanding.
- Card B: naming the member above and identifying the smaller Birch gap supports fairness understanding. Birch becomes first because the priority weights commute gap more heavily; every town remains feasible. Accept equivalent plain-language explanations, not only numeric recall.
- A preference for Amber, Birch or Cedar is not right/wrong. Code whether the explanation uses the available rent/commute trade-off; do not reward agreement with the ranking.
