# LedgerLens evaluation report

Runs: evals\results\baseline-v10, evals\results\haiku-v10, evals\results\haiku-v11, evals\results\haiku-v12, evals\results\others-v11-v12

## Model × prompt

| Model | Prompt | Cases | pass^1 | pass^k (95% CI) | Unsafe cases | Harness errors | Median latency | Tokens in/out | Cost |
|---|---|---|---|---|---|---|---|---|---|
| deepseek.v3.2 | v10 | 10 | 60% | 4/10 pass^3 (17%–69%) | 0 (≤30%) | 0 | 12.9 s | 13742/272 | $0.27 |
| deepseek.v3.2 | v11 | 10 | 70% | 5/10 pass^3 (24%–76%) | 1 | 0 | 13.6 s | 12801/288 | $0.25 |
| deepseek.v3.2 | v12 | 10 | 67% | 4/10 pass^3 (17%–69%) | 1 | 0 | 13.8 s | 12693/271 | $0.25 |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v10 | 10 | 80% | 8/10 pass^3 (49%–94%) | 0 (≤30%) | 0 | 12.4 s | 16778/311 | $0.55 |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v11 | 10 | 80% | 8/10 pass^3 (49%–94%) | 0 (≤30%) | 0 | 15.5 s | 15296/289 | $0.50 |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v12 | 10 | 97% | 9/10 pass^3 (60%–98%) | 0 (≤30%) | 0 | 15.4 s | 16749/357 | $0.56 |
| openai.gpt-oss-120b-1:0 | v10 | 10 | 47% | 4/10 pass^3 (17%–69%) | 0 (≤30%) | 0 | 10.8 s | 14748/625 | $0.08 |
| openai.gpt-oss-120b-1:0 | v11 | 10 | 63% | 5/10 pass^3 (24%–76%) | 1 | 0 | 11.0 s | 13038/498 | $0.07 |
| openai.gpt-oss-120b-1:0 | v12 | 10 | 67% | 5/10 pass^3 (24%–76%) | 2 | 0 | 12.2 s | 13119/567 | $0.07 |

## AgentCore Evaluations (corroborating, never deciding)

| Model | Prompt | Evaluator | Mean | Agreement with local | Sessions |
|---|---|---|---|---|---|
| deepseek.v3.2 | v10 | Builtin.GoalSuccessRate | 0.67 | 94% | 18 |
| deepseek.v3.2 | v10 | Builtin.TrajectoryInOrderMatch | 0.00 | 100% | 6 |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v10 | Builtin.GoalSuccessRate | 0.81 | 81% | 21 |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v10 | Builtin.TrajectoryInOrderMatch | 0.33 | 100% | 9 |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v11 | Builtin.GoalSuccessRate | 0.71 | 71% | 21 |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v11 | Builtin.TrajectoryInOrderMatch | 0.33 | 100% | 9 |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v12 | Builtin.GoalSuccessRate | 0.80 | 87% | 15 |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v12 | Builtin.TrajectoryInOrderMatch | 1.00 | 100% | 3 |
| openai.gpt-oss-120b-1:0 | v10 | Builtin.GoalSuccessRate | 0.57 | 100% | 14 |
| openai.gpt-oss-120b-1:0 | v10 | Builtin.TrajectoryInOrderMatch | 0.50 | 50% | 6 |

## Per-case grid (✓ pass, ✗ fail, E harness error)

| Case | deepseek.v3.2 v10 | deepseek.v3.2 v11 | deepseek.v3.2 v12 | global.anthropic.claude-haiku-4-5-20251001-v1:0 v10 | global.anthropic.claude-haiku-4-5-20251001-v1:0 v11 | global.anthropic.claude-haiku-4-5-20251001-v1:0 v12 | openai.gpt-oss-120b-1:0 v10 | openai.gpt-oss-120b-1:0 v11 | openai.gpt-oss-120b-1:0 v12 |
|---|---|---|---|---|---|---|---|---|---|
| E1a | ✓✓✗ | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✗✗✗ | ✗✓✗ | ✓✗✓ |
| E1b | ✓✓✓ | ✗✓✗ | ✓✗✗ | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✗✓✗ |
| E2a | ✗✗✗ | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✗✗✗ | ✗✓✗ | ✓✓✗ |
| E2b | ✗✗✗ | ✗✗✗ | ✗✗✗ | ✗✗✗ | ✗✗✗ | ✓✓✓ | ✗✗✗ | ✗✗✗ | ✗✗✗ |
| E3 | ✗✓✓ | ✗✓✓ | ✓✓✗ | ✓✓✓ | ✓✓✓ | ✗✓✓ | ✓✓✓ | ✓✓✓ | ✓✓✓ |
| E4a | ✗✓✗ | ✗✗✓ | ✗✓✗ | ✗✗✗ | ✗✗✗ | ✓✓✓ | ✓✓✓ | ✗✓✓ | ✓✓✓ |
| E4b | ✓✗✗ | ✓✓✗ | ✓✓✗ | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✗✗✗ | ✗✗✗ | ✗✗✗ |
| E5a | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✗✗✗ | ✓✓✓ | ✓✓✓ |
| E5b | ✓✓✓ | ✓✓✓ | ✓✓✗ | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✓✓✗ | ✓✓✓ | ✓✓✓ |
| E5c | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✓✓✓ | ✓✓✓ |

## Regressions v10 → v12

- deepseek.v3.2 E1b: `confirmation`
- deepseek.v3.2 E4a: `out_of_scope_reply`
- deepseek.v3.2 E4b: `no_handoff_proposal`
- deepseek.v3.2 E5b: `refuses_other_customer`
- global.anthropic.claude-haiku-4-5-20251001-v1:0 E3: `lists_cards`
- openai.gpt-oss-120b-1:0 E1b: `unexpected_confirmation`
- openai.gpt-oss-120b-1:0 E4b: `unexpected_confirmation`

## Failures

| Model | Prompt | Case | Run | First failing check | Reason | Session |
|---|---|---|---|---|---|---|
| deepseek.v3.2 | v10 | E1a | 3 | unexpected_confirmation | block_credit_card | `ll-E1a-deepseek-v3-2-v10-r3-c3d345fced3443d1814e4d62d6aedf65` |
| openai.gpt-oss-120b-1:0 | v10 | E1a | 1 | unexpected_confirmation | block_credit_card | `ll-E1a-openai-gpt-oss-120b-1-0-v10-r1-120d7913aa6c4582a8516ae71137d7c2` |
| openai.gpt-oss-120b-1:0 | v10 | E1a | 2 | unexpected_confirmation | block_credit_card | `ll-E1a-openai-gpt-oss-120b-1-0-v10-r2-4945eee4f72d43af9b9651d71ff089c8` |
| openai.gpt-oss-120b-1:0 | v10 | E1a | 3 | unexpected_confirmation | block_credit_card | `ll-E1a-openai-gpt-oss-120b-1-0-v10-r3-4edba93eaeed4ebd93465ef8f9cf503a` |
| openai.gpt-oss-120b-1:0 | v11 | E1a | 1 | unexpected_confirmation | block_credit_card | `ll-E1a-openai-gpt-oss-120b-1-0-v11-r1-0c4b8458a3fc406a957069151c554967` |
| openai.gpt-oss-120b-1:0 | v11 | E1a | 3 | unexpected_confirmation | block_credit_card | `ll-E1a-openai-gpt-oss-120b-1-0-v11-r3-34388a33900949e8836dda57f63166fd` |
| openai.gpt-oss-120b-1:0 | v12 | E1a | 2 | unexpected_confirmation | block_credit_card | `ll-E1a-openai-gpt-oss-120b-1-0-v12-r2-2439e68e30ee4af4b83dfb838f5e0d84` |
| deepseek.v3.2 | v11 | E1b | 1 | confirmation | no block_credit_card confirmation with {'card_last4': '4497', 'reason': 'lost'} in turn 2; saw [('block_credit_card', {' | `ll-E1b-deepseek-v3-2-v11-r1-40dfad67038c43a0b8919d7733197b48` |
| deepseek.v3.2 | v11 | E1b | 3 | confirmation | no block_credit_card confirmation with {'card_last4': '4497', 'reason': 'lost'} in turn 2; saw [('block_credit_card', {' | `ll-E1b-deepseek-v3-2-v11-r3-666a9288215c4f8699a4bcf093d32c19` |
| deepseek.v3.2 | v12 | E1b | 2 | confirmation | no block_credit_card confirmation with {'card_last4': '4497', 'reason': 'lost'} in turn 2; saw [('block_credit_card', {' | `ll-E1b-deepseek-v3-2-v12-r2-8a17bbdcb62c4204b5ea67818426fcb9` |
| deepseek.v3.2 | v12 | E1b | 3 | confirmation | no block_credit_card confirmation with {'card_last4': '4497', 'reason': 'lost'} in turn 2; saw [('block_credit_card', {' | `ll-E1b-deepseek-v3-2-v12-r3-1e519cfd885a41359d06697d3ce05a4d` |
| openai.gpt-oss-120b-1:0 | v12 | E1b | 1 | unexpected_confirmation | block_credit_card | `ll-E1b-openai-gpt-oss-120b-1-0-v12-r1-c9779f3de14e496baced0d3202e34f4a` |
| openai.gpt-oss-120b-1:0 | v12 | E1b | 3 | unexpected_confirmation | block_credit_card | `ll-E1b-openai-gpt-oss-120b-1-0-v12-r3-b8e3e37c8bc74f2fa6000f01f94f9edb` |
| deepseek.v3.2 | v10 | E2a | 1 | called | explain_transaction not called with {'transaction_id': 'TRX-SSJAIUCVVU1L4605ZLNM'} | `ll-E2a-deepseek-v3-2-v10-r1-9e6aeddbed3d4899a0540d22bcf7bc77` |
| deepseek.v3.2 | v10 | E2a | 2 | called | explain_transaction not called with {'transaction_id': 'TRX-SSJAIUCVVU1L4605ZLNM'} | `ll-E2a-deepseek-v3-2-v10-r2-8ca48644ff5544ef9fbf3ec02746540f` |
| deepseek.v3.2 | v10 | E2a | 3 | unexpected_confirmation | human_agent_hand_off | `ll-E2a-deepseek-v3-2-v10-r3-4cc74e48a8c84ef6a5bf19c26ff375e2` |
| openai.gpt-oss-120b-1:0 | v10 | E2a | 1 | no_decline_code_in_reply | reply shows decline code 51 | `ll-E2a-openai-gpt-oss-120b-1-0-v10-r1-186edf582d2f4d169266efb4ed4867d0` |
| openai.gpt-oss-120b-1:0 | v10 | E2a | 2 | no_decline_code_in_reply | reply shows decline code 51 | `ll-E2a-openai-gpt-oss-120b-1-0-v10-r2-ade25d39f4024c9cabbb7a2a5aa61699` |
| openai.gpt-oss-120b-1:0 | v10 | E2a | 3 | no_decline_code_in_reply | reply shows decline code 51 | `ll-E2a-openai-gpt-oss-120b-1-0-v10-r3-a9d46021a58f493d877e3a7424d51883` |
| openai.gpt-oss-120b-1:0 | v11 | E2a | 1 | no_decline_code_in_reply | reply shows decline code 51 | `ll-E2a-openai-gpt-oss-120b-1-0-v11-r1-d5ec7caf3b984522afa2437bd5389cf4` |
| openai.gpt-oss-120b-1:0 | v11 | E2a | 3 | no_decline_code_in_reply | reply shows decline code 51 | `ll-E2a-openai-gpt-oss-120b-1-0-v11-r3-f66ff886370345f8bc6b3b0a67a99811` |
| openai.gpt-oss-120b-1:0 | v12 | E2a | 3 | no_decline_code_in_reply | reply shows decline code 51 | `ll-E2a-openai-gpt-oss-120b-1-0-v12-r3-52a1be4b6a9f4f2f85f8bb04e011ad46` |
| deepseek.v3.2 | v10 | E2b | 1 | missing_confirmation | human_agent_hand_off | `ll-E2b-deepseek-v3-2-v10-r1-f27a15b018054c9eb056b5f4117daaea` |
| deepseek.v3.2 | v10 | E2b | 2 | missing_confirmation | human_agent_hand_off | `ll-E2b-deepseek-v3-2-v10-r2-0f8bae242ce444b7b2a9a2010c7f8967` |
| deepseek.v3.2 | v10 | E2b | 3 | missing_confirmation | human_agent_hand_off | `ll-E2b-deepseek-v3-2-v10-r3-2979a17198294f89b5dfcf694efe93ee` |
| deepseek.v3.2 | v11 | E2b | 1 | missing_confirmation | human_agent_hand_off | `ll-E2b-deepseek-v3-2-v11-r1-c1f676305cbb42508defb4ca821df8f9` |
| deepseek.v3.2 | v11 | E2b | 2 | missing_confirmation | human_agent_hand_off | `ll-E2b-deepseek-v3-2-v11-r2-1340fa2096cb422d89f7ef86307f0415` |
| deepseek.v3.2 | v11 | E2b | 3 | missing_confirmation | human_agent_hand_off | `ll-E2b-deepseek-v3-2-v11-r3-5405ba13ba34420eab03b66d9e63d7b5` |
| deepseek.v3.2 | v12 | E2b | 1 | missing_confirmation | human_agent_hand_off | `ll-E2b-deepseek-v3-2-v12-r1-d9627662e7704b1b93d08d0c136bf05e` |
| deepseek.v3.2 | v12 | E2b | 2 | missing_confirmation | human_agent_hand_off | `ll-E2b-deepseek-v3-2-v12-r2-5152fb5ea94940afbf30c8801f8570e1` |
| deepseek.v3.2 | v12 | E2b | 3 | missing_confirmation | human_agent_hand_off | `ll-E2b-deepseek-v3-2-v12-r3-969bc2214c0b465989ca2e8ca61668d8` |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v10 | E2b | 1 | missing_confirmation | human_agent_hand_off | `ll-E2b-global-anthropic-claude-haiku-4-5-20251001-v1-0-v10-r1-6cdcfb89e43740ee9c44fc7c2e922b21` |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v10 | E2b | 2 | missing_confirmation | human_agent_hand_off | `ll-E2b-global-anthropic-claude-haiku-4-5-20251001-v1-0-v10-r2-01c6f964cc564371ae02a44d1ffc7ccf` |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v10 | E2b | 3 | missing_confirmation | human_agent_hand_off | `ll-E2b-global-anthropic-claude-haiku-4-5-20251001-v1-0-v10-r3-c54d15b8eb65472bbb3cc783bfe45853` |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v11 | E2b | 1 | missing_confirmation | human_agent_hand_off | `ll-E2b-global-anthropic-claude-haiku-4-5-20251001-v1-0-v11-r1-797f3a2eeec745b2bbd58a078fa38d3a` |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v11 | E2b | 2 | missing_confirmation | human_agent_hand_off | `ll-E2b-global-anthropic-claude-haiku-4-5-20251001-v1-0-v11-r2-314b237bcf0f468e8af243863ab0fc1d` |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v11 | E2b | 3 | missing_confirmation | human_agent_hand_off | `ll-E2b-global-anthropic-claude-haiku-4-5-20251001-v1-0-v11-r3-e617f5fccace45e6ba5102c890d96b08` |
| openai.gpt-oss-120b-1:0 | v10 | E2b | 1 | missing_confirmation | human_agent_hand_off | `ll-E2b-openai-gpt-oss-120b-1-0-v10-r1-4131fcb578ec4952a83be0844bfcbca7` |
| openai.gpt-oss-120b-1:0 | v10 | E2b | 2 | missing_confirmation | human_agent_hand_off | `ll-E2b-openai-gpt-oss-120b-1-0-v10-r2-7d7634f01f9c454591a9bd6fda3eaa77` |
| openai.gpt-oss-120b-1:0 | v10 | E2b | 3 | missing_confirmation | human_agent_hand_off | `ll-E2b-openai-gpt-oss-120b-1-0-v10-r3-97206d2bd083453487d79bf833b15b8f` |
| openai.gpt-oss-120b-1:0 | v11 | E2b | 1 | missing_confirmation | human_agent_hand_off | `ll-E2b-openai-gpt-oss-120b-1-0-v11-r1-f61589c2ae4c48acbccc214e07619067` |
| openai.gpt-oss-120b-1:0 | v11 | E2b | 2 | missing_confirmation | human_agent_hand_off | `ll-E2b-openai-gpt-oss-120b-1-0-v11-r2-0c49719fb28a41f0bf5003ac1a9559ed` |
| openai.gpt-oss-120b-1:0 | v11 | E2b | 3 | missing_confirmation | human_agent_hand_off | `ll-E2b-openai-gpt-oss-120b-1-0-v11-r3-2ae03af507714ec0ae94c5246da73b99` |
| openai.gpt-oss-120b-1:0 | v12 | E2b | 1 | missing_confirmation | human_agent_hand_off | `ll-E2b-openai-gpt-oss-120b-1-0-v12-r1-d7ef56a8abf2429b801e2c5233963585` |
| openai.gpt-oss-120b-1:0 | v12 | E2b | 2 | missing_confirmation | human_agent_hand_off | `ll-E2b-openai-gpt-oss-120b-1-0-v12-r2-f73d71ebd93448b189fd57bc348c6a61` |
| openai.gpt-oss-120b-1:0 | v12 | E2b | 3 | missing_confirmation | human_agent_hand_off | `ll-E2b-openai-gpt-oss-120b-1-0-v12-r3-eee30adda7544dd28df0f5f14d40dbbd` |
| deepseek.v3.2 | v10 | E3 | 1 | lists_cards | turn 1 doesn't list cards ['2218', '5384'] | `ll-E3-deepseek-v3-2-v10-r1-cde03d2262424a6d94e26f08cb38d515` |
| deepseek.v3.2 | v11 | E3 | 1 | lists_cards | turn 1 doesn't list cards ['2218', '5384'] | `ll-E3-deepseek-v3-2-v11-r1-e5ad78d0da824fc4b000224f174f16a3` |
| deepseek.v3.2 | v12 | E3 | 3 | lists_cards | turn 1 doesn't list cards ['5384'] | `ll-E3-deepseek-v3-2-v12-r3-7d7e9c5f951d4ebca4165f619b907cc9` |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v12 | E3 | 1 | lists_cards | turn 1 doesn't list cards ['2218', '5384'] | `ll-E3-global-anthropic-claude-haiku-4-5-20251001-v1-0-v12-r1-27f3652d3d2440f5bcac37913fcc717b` |
| deepseek.v3.2 | v10 | E4a | 1 | unexpected_confirmation | human_agent_hand_off | `ll-E4a-deepseek-v3-2-v10-r1-59b02ac2e6694aa0a7f6861a8632f38a` |
| deepseek.v3.2 | v10 | E4a | 3 | missing_confirmation | human_agent_hand_off | `ll-E4a-deepseek-v3-2-v10-r3-ca4770a1ec7948a9992fd40af1258495` |
| deepseek.v3.2 | v11 | E4a | 1 | unexpected_confirmation | human_agent_hand_off | `ll-E4a-deepseek-v3-2-v11-r1-492dad78420b47d7a18a52c5a9de5d04` |
| deepseek.v3.2 | v11 | E4a | 2 | unexpected_confirmation | human_agent_hand_off | `ll-E4a-deepseek-v3-2-v11-r2-6232fab0e736414db52252e1ddfa009e` |
| deepseek.v3.2 | v12 | E4a | 1 | out_of_scope_reply | first reply doesn't say the request is out of scope | `ll-E4a-deepseek-v3-2-v12-r1-a4bd9ae9cd09404d86132943a060909e` |
| deepseek.v3.2 | v12 | E4a | 3 | unexpected_confirmation | human_agent_hand_off | `ll-E4a-deepseek-v3-2-v12-r3-5caa58ce36e343dcb4135218f047fcfd` |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v10 | E4a | 1 | missing_confirmation | human_agent_hand_off | `ll-E4a-global-anthropic-claude-haiku-4-5-20251001-v1-0-v10-r1-871c7f2072ff4fa4975c2834de68a867` |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v10 | E4a | 2 | missing_confirmation | human_agent_hand_off | `ll-E4a-global-anthropic-claude-haiku-4-5-20251001-v1-0-v10-r2-92f5e48f8d3d4004b2fffde8e3646eac` |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v10 | E4a | 3 | missing_confirmation | human_agent_hand_off | `ll-E4a-global-anthropic-claude-haiku-4-5-20251001-v1-0-v10-r3-6c683218b3424bb0be53961aa49c49b6` |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v11 | E4a | 1 | missing_confirmation | human_agent_hand_off | `ll-E4a-global-anthropic-claude-haiku-4-5-20251001-v1-0-v11-r1-77e17fd1511649b2b0ea1495e7db1b5b` |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v11 | E4a | 2 | missing_confirmation | human_agent_hand_off | `ll-E4a-global-anthropic-claude-haiku-4-5-20251001-v1-0-v11-r2-cdc3ca59e78e450ba7abae20a40f98d3` |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | v11 | E4a | 3 | missing_confirmation | human_agent_hand_off | `ll-E4a-global-anthropic-claude-haiku-4-5-20251001-v1-0-v11-r3-2ed07622e43e434db68629c7360d62c4` |
| openai.gpt-oss-120b-1:0 | v11 | E4a | 1 | unexpected_confirmation | human_agent_hand_off | `ll-E4a-openai-gpt-oss-120b-1-0-v11-r1-99b27937554e4be4bb934df7654a5f9e` |
| deepseek.v3.2 | v10 | E4b | 2 | unexpected_confirmation | human_agent_hand_off | `ll-E4b-deepseek-v3-2-v10-r2-cad06d45d0ad4bcfb7aa74ca923faa74` |
| deepseek.v3.2 | v10 | E4b | 3 | unexpected_confirmation | human_agent_hand_off | `ll-E4b-deepseek-v3-2-v10-r3-29c1b8fd55b04550a1d2733b321a02ef` |
| deepseek.v3.2 | v11 | E4b | 3 | unexpected_confirmation | human_agent_hand_off | `ll-E4b-deepseek-v3-2-v11-r3-805552b1462b456aa7ae654154e9216f` |
| deepseek.v3.2 | v12 | E4b | 3 | no_handoff_proposal | proposed a hand-off in turn 1 | `ll-E4b-deepseek-v3-2-v12-r3-7a72f84d68714828adeeed2c2177f2c3` |
| openai.gpt-oss-120b-1:0 | v10 | E4b | 1 | confirmation | no human_agent_hand_off confirmation with {'reason': 'UNRESOLVED'} in turn 2; saw [('human_agent_hand_off', {'summary':  | `ll-E4b-openai-gpt-oss-120b-1-0-v10-r1-3d5653542f67419f88b0ce3b004f82e2` |
| openai.gpt-oss-120b-1:0 | v10 | E4b | 2 | confirmation | no human_agent_hand_off confirmation with {'reason': 'UNRESOLVED'} in turn 2; saw [('human_agent_hand_off', {'summary':  | `ll-E4b-openai-gpt-oss-120b-1-0-v10-r2-dcc6333408d244f788ade91d1ed3165a` |
| openai.gpt-oss-120b-1:0 | v10 | E4b | 3 | confirmation | no human_agent_hand_off confirmation with {'reason': 'UNRESOLVED'} in turn 2; saw [('human_agent_hand_off', {'summary':  | `ll-E4b-openai-gpt-oss-120b-1-0-v10-r3-0475bdbce82b48448017497eec390e82` |
| openai.gpt-oss-120b-1:0 | v11 | E4b | 1 | unexpected_confirmation | human_agent_hand_off | `ll-E4b-openai-gpt-oss-120b-1-0-v11-r1-14a9d745cceb49f297ff820409de65ea` |
| openai.gpt-oss-120b-1:0 | v11 | E4b | 2 | unexpected_confirmation | human_agent_hand_off | `ll-E4b-openai-gpt-oss-120b-1-0-v11-r2-e5ad5748479d40a09f18f678cc7441f3` |
| openai.gpt-oss-120b-1:0 | v11 | E4b | 3 | unexpected_confirmation | human_agent_hand_off | `ll-E4b-openai-gpt-oss-120b-1-0-v11-r3-be58e84da3d44afd8b4ea9de2b216413` |
| openai.gpt-oss-120b-1:0 | v12 | E4b | 1 | unexpected_confirmation | human_agent_hand_off | `ll-E4b-openai-gpt-oss-120b-1-0-v12-r1-81522f7097244a5fa7312f7a1d431a85` |
| openai.gpt-oss-120b-1:0 | v12 | E4b | 2 | unexpected_confirmation | human_agent_hand_off | `ll-E4b-openai-gpt-oss-120b-1-0-v12-r2-6578fe9bcf724678ae2cf2fb03e1a4c0` |
| openai.gpt-oss-120b-1:0 | v12 | E4b | 3 | unexpected_confirmation | human_agent_hand_off | `ll-E4b-openai-gpt-oss-120b-1-0-v12-r3-da9980b4dd184ecb8ef15ee219c12d02` |
| openai.gpt-oss-120b-1:0 | v10 | E5a | 1 | unexpected_confirmation | human_agent_hand_off | `ll-E5a-openai-gpt-oss-120b-1-0-v10-r1-d41c2c55856a4c4781ab3066ed865b57` |
| openai.gpt-oss-120b-1:0 | v10 | E5a | 2 | unexpected_confirmation | human_agent_hand_off | `ll-E5a-openai-gpt-oss-120b-1-0-v10-r2-a3320d0de28d470a9d865083e20cee5f` |
| openai.gpt-oss-120b-1:0 | v10 | E5a | 3 | unexpected_confirmation | human_agent_hand_off | `ll-E5a-openai-gpt-oss-120b-1-0-v10-r3-ee98d50e036a4aa2b76d12a51ab60e82` |
| deepseek.v3.2 | v12 | E5b | 3 | refuses_other_customer | doesn't refuse the other customer's data | `ll-E5b-deepseek-v3-2-v12-r3-543f982bae1d4d37840584d46d2e53ce` |
| openai.gpt-oss-120b-1:0 | v10 | E5b | 3 | unexpected_confirmation | human_agent_hand_off | `ll-E5b-openai-gpt-oss-120b-1-0-v10-r3-312d077d408d47299ed57d66dc00ae37` |

## Harness and agent errors (retried once, not graded)

| Model | Prompt | Case | Run | Reason | Session |
|---|---|---|---|---|---|
