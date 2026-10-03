# Learned components with valid labels for a Spanish + Portuguese banking customer-service agent (external data, since the organizer's synthetic dataset cannot supply them)

Scope note: research as of 2026-09-29. The team has already established that the organizer's LATAM Bank dataset can't be used for learning: transcripts come from 2 templates, there is no Portuguese, the fraud labels only become learnable with a leaking score, the matcher baseline already reaches 99.6% top-3, and the priority/SLA labels are random. That is not re-checked here. Wherever a dataset below is machine-translated, synthetic (LLM-generated), research-only or non-commercial, it is flagged. The concrete design cards (task, labels, data, baseline, metrics, split, effort) are under the Inferences of the key question "Small, cheap learned components".

## Public labelled Spanish/Portuguese datasets for banking intent classification and out-of-scope (OOS) detection

### Takeaway
No public intent corpus in LATAM Spanish (es-419) or Brazilian Portuguese (pt-BR) banking was found. The credible human-labelled options are **MINDS-14** (real spoken e-banking utterances in es-ES and pt-PT, CC-BY-4.0, but small: about 50 per intent per language, and near ceiling at 92–97% accuracy), **Multi3NLU++** (3,080 banking and hotel utterances per language, professionally translated into Spanish, multi-label with 62 intents, CC-BY-4.0, no Portuguese), and **MASSIVE** (es-ES and pt-PT, human-localized, no banking domain, so it is useful only as out-of-scope negatives). Banking77 and CLINC150 are English only.

### Cited Findings
**MINDS-14 (PolyAI)**
- Covers 14 locales, including **es-ES and pt-PT**. There is no pt-BR variant. — [HF card PolyAI/minds14](https://huggingface.co/datasets/PolyAI/minds14)
- License is CC-BY-4.0. The card reports 16,336 rows across configurations and 471 MB. It includes native-language transcriptions plus an English transcription for each sample. — [HF card](https://huggingface.co/datasets/PolyAI/minds14)
- The 14 intents were "sampled from a set of 90+ fine-grained intents used by a commercial banking voice assistant". About 50 examples were collected per intent per language variety. — [Gerz et al., EMNLP 2021 (PDF)](https://aclanthology.org/2021.emnlp-main.591.pdf)
- **Collection method:** crowdsourced native speakers on Prolific were given the intent, a description and 3 examples, then asked to produce new spoken utterances. This is elicited speech, not real customer calls. Two protocols were used: (1) a phone-based voice assistant that participants called (IT, and parts of DE, **PT**, PL, EN-AU), and (2) online recording through Phonic (all remaining data). Personal names and sensitive content were removed by hand. The release includes the original speech plus ASR transcripts (Google ASR n-best). — [Gerz et al. 2021](https://aclanthology.org/2021.emnlp-main.591.pdf)
  - Conflict: the HF card summary describes the data as speech "collected as part of a commercial system". The paper says only the intent inventory comes from a commercial system; the utterances were crowdsourced. — [HF card](https://huggingface.co/datasets/PolyAI/minds14) vs [paper](https://aclanthology.org/2021.emnlp-main.591.pdf)
- Intents confirmed in search snippets include BUSINESS_LOAN, FREEZE, ABROAD, APP_ERROR, CARD_ISSUES, ATM_LIMIT and ADDRESS. — [DeepPavlov/minds14 (search snippet)](https://huggingface.co/datasets/DeepPavlov/minds14)
- **Baseline and ceiling (accuracy × 100):** a fixed LaBSE encoder with a 2-layer MLP, evaluated with 3-fold CV on random 60/40 splits and averaged over 3 runs, scores:
  - translate-to-EN, no auxiliary data: **ES 95.8, PT 97.5**
  - target-only (native language) LaBSE: **ES 91.9, PT 95.3**
  - multilingual LaBSE: **ES 91.5, PT 92.7**
  - training only on auxiliary English data translated to the target language: **ES 62.7, PT 53.1**
  — [Gerz et al. 2021, Table 1](https://aclanthology.org/2021.emnlp-main.591.pdf)
- The paper follows Casanueva et al. (2020) in using fixed sentence encoders plus an MLP, which the authors say performs "on-par with the full-model fine-tuning" at far lower cost. — [Gerz et al. 2021](https://aclanthology.org/2021.emnlp-main.591.pdf)
- Standard MINDS-14 splits are also distributed inside Google's XTREME-S benchmark (`minds14_splits/*.tsv`). — [google/xtreme_s](https://huggingface.co/datasets/google/xtreme_s/blob/6689ba8f1044a59f860da50852eca5f09a01f8f2/minds14_splits/dev_en-AU.tsv)

**Multi3NLU++ (Edinburgh/PolyAI)**
- License CC-BY-4.0.
- Languages are English plus **Spanish**, Turkish, Marathi and Amharic. There is no Portuguese.
- Domains are BANKING and HOTELS. There are 62 intents, and the task is multi-label with slots. Each language has 3,080 utterances.
- Translations were done by "Professionally translated … Blend Express and Proz.com". — [HF uoe-nlp/multi3-nlu](https://huggingface.co/datasets/uoe-nlp/multi3-nlu)
- There are 23 banking-specific intents plus 39 generic ones. Examples cover card requests, lost/stolen cards, blocking, disputes and transfers.
- Translators were told to treat the task as creative writing and keep colloquial language.
- Protocol: N-fold CV with 20-fold (low data), 10-fold (mid data) and 10-fold reversed (large data). Metric is micro-F1. Models were XLM-R, LaBSE/mpnet with an MLP, and QA-style mDeBERTa.
- Translate-test with M2M100 was poor.
- As extracted, Spanish LaBSE banking reaches about 64.0 F1 vs English 64.3 in one 10-fold setting.
- All of the above is from [arXiv 2212.10455 (HTML)](https://arxiv.org/html/2212.10455) and [ACL Findings 2023](https://aclanthology.org/2023.findings-acl.230/).

**MASSIVE (Amazon)**
- Covers 52 languages, including **es-ES and pt-PT**. There is no pt-BR or es-419.
- Each locale has 11,514 train, 2,033 dev and 2,974 test utterances, with 60 intents, 18 scenarios and 55 slot types.
- The data is a localization of SLURP by MTurk workers. — [HF AmazonScience/massive](https://huggingface.co/datasets/AmazonScience/massive)
- For each slot, workers chose "Translation", "Localization" or "Unchanged". Quality was judged by multiple workers.
- No finance or banking scenario was identified. — [GitHub alexa/massive](https://github.com/alexa/massive)
- License conflict: the HF card states CC-BY-4.0, while the GitHub repo lists Apache 2.0 (plus NOTICE and THIRD-PARTY files). — [HF](https://huggingface.co/datasets/AmazonScience/massive) vs [GitHub](https://github.com/alexa/massive)
- MTEB-PT includes MassiveIntentClassification with a Portuguese subset of 2,974 examples. — [MTEB-PT paper (search snippet)](https://arxiv.org/pdf/2607.04071)

**Banking77 (PolyAI)**
- English only, CC-BY-4.0. It has 10,003 train and 3,080 test examples across 77 fine-grained intents, taken from online-banking customer-service queries. — [HF PolyAI/banking77](https://huggingface.co/datasets/PolyAI/banking77); paper: Casanueva et al. 2020, arXiv:2003.04807
- A search for Spanish or Portuguese translations of Banking77 on HF found only English re-uploads (asbeelagi, Vinline, KhunEduan, betojdk, mteb, DeepPavlov …). — [search results listing](https://huggingface.co/datasets/mteb/banking77)

**CLINC150 (clinc_oos)**
- English, CC-BY-3.0. It has 150 in-scope intents plus 1 out-of-scope class across 10 domains, including banking.
- Splits (train/val/test): Small 7,600 / 3,100 / 5,500; Imbalanced 10,625 / 3,100 / 5,500; Plus 15,250 / 3,100 / 5,500.
- Paper: Larson et al., EMNLP-IJCNLP 2019. — [HF clinc/clinc_oos](https://huggingface.co/datasets/clinc/clinc_oos)

**LATAM Spanish and pt-BR finance resources (not intent-labelled banking corpora)**
- *Portuguese FAQ for Financial Services*: pt-BR question-answer pairs from the Central Bank of Brazil (BACEN) FAQ. License CC BY 4.0, "to be published on Hugging Face". — [arXiv 2311.11331](https://arxiv.org/abs/2311.11331)
  - A search snippet puts it at roughly 2,000 question-answer pairs from dadosabertos.bcb.gov.br. — [arXiv HTML (search snippet)](https://arxiv.org/html/2311.11331)
- B2T: 1,096 pt-BR tweets about Brazilian banks, labelled for sentiment only. — [ResearchGate](https://www.researchgate.net/publication/384899281_B2T_A_Dataset_of_Tweets_in_Portuguese_Language_about_Brazilian_Banks)
- Bitext retail banking: **English only**, "hybrid synthetic", 26 intents (including block_card, activate_card, cancel_card), 25,545 pairs, license CDLA-Sharing-1.0. — [HF bitext](https://huggingface.co/datasets/bitext/Bitext-retail-banking-llm-chatbot-training-dataset)

**Code-switching (Portuñol)**
- The only material found was linguistics research on Portuguese–Spanish code-switching: border communities, Misiones (Argentina), and playful or ironic switching. **No NLP-ready labelled Portuñol corpus was found.** — [Benjamins chapter](https://benjamins.com/catalog/ihll.22.10lip); [ResearchGate: playful divergences](https://www.researchgate.net/publication/364050079_On_playful_language_divergences_Code-switching_among_Spanish-Portuguese_bilinguals)

### Inferences
- **Best human-labelled intent source for this workflow: MINDS-14 es-ES + pt-PT.**
  - It is genuinely spoken, so it fits the voice-agent story.
  - Its intents overlap the card workflow: CARD_ISSUES, FREEZE, ABROAD, ATM_LIMIT, ADDRESS, APP_ERROR.
  - Weakness: published accuracies of 92–97% leave little headroom, much like the 99.6% matcher problem. A judge could call it too easy. **The defensible contribution is therefore OOS/abstention and calibration, not raw accuracy.**
- **Multi3NLU++ Spanish is harder and closer to the workflow** (blocking, lost/stolen, disputes), with low-data F1 in the 60s. It is professionally translated from English, not natively written. Flag it as "human-translated" in the provenance table.
- **Portuguese coverage is pt-PT only** (MINDS-14, MASSIVE). No public pt-BR banking intent test set exists, so any pt-BR evaluation needs a small team-written, team-labelled set. Label it "team-generated" and report it separately.
- **Parallel-corpus leakage trap.** MASSIVE and Multi3NLU++ are parallel: the same utterance ID appears in several languages. If a multilingual model trains on the English or Spanish version of a test item, test scores inflate. Split by **utterance ID across all languages** (GroupKFold on ID).
- **MINDS-14 speaker leakage.** The paper uses random 60/40 splits. It was not verified whether speaker IDs are exposed. If they are, group by speaker.
- **Banking77 and CLINC150 in ES/PT** would have to be machine-translated by the team. Use them only for training augmentation, flagged "team-generated MT", never as the test set.
- **Portuñol:** the only honest option is a small team-authored stress set (e.g., 50–100 utterances) reported as a qualitative robustness probe, not a headline metric.

### Gaps
- The full MINDS-14 intent list could not be verified from a primary source. Only 7 of the 14 names were confirmed (via a search snippet). It is also unconfirmed whether speaker IDs are included, which matters for grouped splits.
- The paper's consent text says the data "will be used for experimental research purposes", while the release is CC-BY-4.0. No explicit commercial restriction was found.
- MASSIVE's intent list was not fetched, so the absence of banking-like intents (e.g., the `qa_*` or `general_*` families) was not checked line by line.
- The BACEN FAQ dataset's actual HF location and final size were not verified.
- No Spanish (es-419) or pt-BR banking intent corpus with native, human-written utterances was found on HF or in the papers searched.

## Public complaint datasets with labels for complaint category / product / issue classification

### Takeaway
Only the **CFPB** database pairs free-text complaint narratives with product, sub-product, issue and sub-issue labels, and it is English. On **14 Aug 2026 the CFPB stopped publishing new narratives**, and the historical ones (Dec 2011–14 Aug 2026) were moved to a FOIA Reading Room archive. The LATAM sources (consumidor.gov.br, SFC Colombia, CONDUSEF) supply **label taxonomies and base rates**, not labelled text. None of them offers verified downloadable narratives.

### Cited Findings
**CFPB (USA)**
- Published fields are product, sub-product, issue, sub-issue, and consumer narratives. Narratives are opt-in and scrubbed of PII.
- The data is "freely available for anyone to use, analyze, and build on", and the CFPB warns it "is not a statistical sample of consumers' experiences". — [CFPB Consumer Complaint Database](https://www.consumerfinance.gov/data-research/consumer-complaints/)
- On **14 Aug 2026** the CFPB announced it would stop "discretionary publication of unverified complaint narratives and visualizations". It considers previously published narratives public domain for FOIA purposes and placed them in the FOIA Reading Room. — [CFPB newsroom](https://www.consumerfinance.gov/about-us/newsroom/the-cfpb-to-cease-discretionary-publication-of-complaint-narratives-and-visualizations/); [law-firm summary](https://www.consumerfinancialserviceslawmonitor.com/2026/08/cfpb-ends-publication-of-consumer-complaint-narratives-and-data-visualizations/)
- The archive covers "complaints received December 1, 2011 through August 14, 2026 that were previously published", as monthly and multi-month ZIP exports (latest "CCDB Export August 2026"). No archive-specific terms of use are stated. — [CFPB FOIA narratives archive](https://www.consumerfinance.gov/foia-requests/foia-electronic-reading-room/cfpb-consumer-complaint-database-narratives-archive/)
- The dataset is also listed on data.gov. — [catalog.data.gov](https://catalog.data.gov/dataset/consumer-complaint-database)

**Brazil – consumidor.gov.br (Senacon/MJSP)**
- Open data is monthly CSV from 2014 onward. Fields include company, segment, area, subject (assunto), problem group (grupo problema), problem (problema), state/city, status, rating and deadlines.
- Consumers' personal data is protected. — [consumidor.gov.br "Como funciona"](https://www.consumidor.gov.br/pages/conteudo/publico/1) and search summaries
- The public portal's "Relato do Consumidor" tab lets anyone *read* complaint text, company responses and final consumer comments, searchable by keyword, segment and supplier. — [consumidor.gov.br](https://www.consumidor.gov.br/pages/conteudo/publico/1)
- A dados.gov.br resource titled "Dados Consumidor.gov.br – Relato do Consumidor – 2020" exists, but it returned HTTP 401, so its contents could not be verified. — [dados.gov.br resource](https://dados.gov.br/dataset/reclamacoes-do-consumidor-gov-br1/resource/1ace37db-7a6e-432c-a79a-cddbf188fd4b)
- The official CSVs have accented column names and semicolon separators. — [reclamacoes-radar](https://github.com/arthurpenedo/reclamacoes-radar)
- The source data is under a CC BY license via dados.gov.br. For the "Bancos, Financeiras e Administradoras de Cartão" segment, about **1.63 M finalized complaints** were recorded Sep 2025–Aug 2026. — [HF dnacx/tres-numeros-de-resolucao-consumidor-gov](https://huggingface.co/datasets/dnacx/tres-numeros-de-resolucao-consumidor-gov)
- An older press item reports that banks, financeiras and card administrators made up about 41% of all complaints. — [Conjur 2021](https://www.conjur.com.br/2021-nov-03/reclamacoes-bancos-dominam-plataforma-consumidorgov/)

**Colombia – Superintendencia Financiera (SFC)**
- The datos.gov.co dataset hjqv-fp48 covers complaints filed with SFC and consumer defenders. Columns:
  - tipo_entidad, codigo_entidad, nombre_entidad, fecha_corte
  - unidad_captura, codigo_producto, **producto**, codigo_motivo, **motivo**
  - quejas_recibidas / finalizadas / pendientes / en_tramite, plus outcome columns
- License is **CC BY-SA 4.0**. Last row update was 21 Mar 2023.
- **It contains aggregated counts and no narrative.** — [Socrata metadata hjqv-fp48](https://www.datos.gov.co/api/views/hjqv-fp48.json); [dataset page](https://www.datos.gov.co/Econom-a-y-Finanzas/Quejas-interpuestas-ante-las-entidades-vigiladas-p/hjqv-fp48)
- A second dataset, y8u7-q37x, has monthly counts before the SmartSupervision launch, by entity type, entity, product, reason and status. — [datos.gov.co y8u7-q37x](https://www.datos.gov.co/Econom-a-y-Finanzas/Quejas-interpuestas-por-los-consumidores-financier/y8u7-q37x/data)

**Mexico – CONDUSEF**
- CONDUSEF runs an open-data portal. The page could not be fetched because of a TLS certificate error. — [condusef.gob.mx datos-abiertos](https://www.condusef.gob.mx/?p=datos-abiertos)
- REDECO is the registry of collection agencies. It receives complaints about abusive collection practices. One report cites 14,046 complaints, 76.82% of them against multiple banking. — [CONDUSEF REDECO](https://www.condusef.gob.mx/?p=redeco); figure from search summary of [CONDUSEF self-evaluation Jan–Jun 2025](https://www.condusef.gob.mx/documentos/transparencia/IA-ENE-JUN-2025.pdf)
- No free-text complaint data was found.

### Inferences
- **The complaint classifier can't be both native-LATAM and learned from real text.** The defensible pattern is cross-lingual transfer:
  - Train on CFPB English narratives, with labels mapped to a compact taxonomy aligned with SFC `producto`/`motivo` and consumidor.gov.br `assunto`/`problema`. Those taxonomies make the label space locally credible.
  - Evaluate on (a) a held-out CFPB English test set and (b) a small **team-written, dual-annotated ES/PT complaint set** (e.g., 100–200 items, flagged team-generated, with inter-annotator agreement reported).
  - Machine-translating CFPB narratives into ES/PT for training is acceptable if flagged as MT.
- **CFPB leakage controls:**
  - Split **temporally** (e.g., train on narratives received before 2025, test on 2025–Aug 2026).
  - De-duplicate near-identical narratives, since many are templated letters.
  - Optionally group by company so the model can't key on company names.
  - Strip the `company`, `issue` and `sub_issue` fields from the inputs when `product` or `issue` is the target.
- **consumidor.gov.br and SFC counts are useful as priors,** e.g., "Cobrança / Contestação" dominating the bank segment. Use them to pick which categories matter and to justify class weighting. They are not training labels for text.
- **Regulator-deadline logic (PQR response times) should stay rule-based.** Present the learned part as category/product routing plus a missing-information detector.

### Gaps
- Whether the consumidor.gov.br open data (the "Relato do Consumidor" resources) contains the narrative text in bulk could not be confirmed. dados.gov.br returned 401 and dados.mj.gov.br did not resolve. The data dictionary PDF could not be read either.
- The exact CFPB archive file format and the number of narratives were not stated on the archive page.
- CONDUSEF open-data contents (e.g., SIGE/REUNE complaint files) could not be enumerated because of the TLS error.
- The license for the CFPB FOIA archive files is not stated. The CFPB only says they are in the "public domain for FOIA purposes".

## Scam/fraud conversation and message datasets for a scam-risk classifier

### Takeaway
Real, human-labelled **pt-BR scam messages** exist in FraudWhatsApp.Br and FraudTelegram.Br, and the **multilingual IMC'25 smishing corpus** (CC BY 4.0) carries scam-type and brand labels. **Scam *dialogue* datasets are synthetic and English/Asian-language only**, and one is non-commercial. None was found in ES or PT. A scam classifier is credible for "is this SMS/WhatsApp I received a scam?" (message level), not for full call transcripts.

### Cited Findings
- **FraudWhatsApp.Br / FraudTelegram.Br (UFC, SBSeg).** Two public labelled datasets of pt-BR messages from public WhatsApp and Telegram groups, containing fraudulent messages.
  - Collection: messages were keyword-filtered first, then labelled **fully by hand by three annotators**, with disagreements resolved by collective review.
  - The best classical-ML F1 was **0.99** on both datasets.
  - Code and data: github.com/jmmfilho/sec-fraudimabr.
  - [SBSeg paper (PDF)](https://sol.sbc.org.br/index.php/sbseg/article/download/27211/27027/)
- **IMC'25 Smishing dataset** (Agarwal, Papasavva, Suarez-Tangil, Vasek, ACM IMC 2025).
  - Labels cover scam types, impersonated brand, lure principles and named entities. The main file is `final_dataset_output.csv`.
  - License is **CC BY 4.0**, with no research-only restriction stated. — [GitHub reportsmishing/Smishing-Dataset-IMC25](https://github.com/reportsmishing/Smishing-Dataset-IMC25)
  - A downstream project describes it as 33,788 messages across 50+ languages (secondary source). — [CocoChengtw/smishing-scam-type-classifier](https://github.com/CocoChengtw/smishing-scam-type-classifier)
- **MOZ-Smishing (AfricaNLP 2025).** Crowd-sourced SMS in **Mozambican Portuguese** labelled ham or smishing, released under "an open license" on HF. LLM in-context learning was evaluated. — [ACL Anthology](https://aclanthology.org/2025.africanlp-1.23/)
- **MIMICS-3500** is a multi-class smishing dataset drawn from Kaggle, Mendeley, SmishTank, SpamHunter and data from Spain's INCIBE. The Spanish content share is unverified. — [ScienceDirect (search result)](https://www.sciencedirect.com/science/article/abs/pii/S0952197625028957)
- **Synthetic scam dialogues:**
  - BothBosu multi-agent-scam-conversation: **English**, 1,600 rows (1.28k train / 320 test), generated with Autogen + Together API, binary scam label plus type, Apache-2.0. — [HF](https://huggingface.co/datasets/BothBosu/multi-agent-scam-conversation)
  - MultiFraudAlign: EN/HI/KO/Hinglish with **no ES/PT**, 28,708 dialogues generated by Qwen2.5-72B, **CC BY-NC 4.0** (non-commercial). — [HF](https://huggingface.co/datasets/ggirishg/MultiFraudAlign)
  - phone-scam-detection-synthetic: 1,800 synthetic English dialogues. — [HF](https://huggingface.co/datasets/shakeleoatmeal/phone-scam-detection-synthetic)
- **Pix fraud.** A 2025 taxonomy paper describes Pix schemes evolving "from purely social engineering approaches to hybrid strategies". It is useful for defining scam-type labels. — [arXiv 2511.20902](https://arxiv.org/abs/2511.20902)
- Spanish-language search turned up only INCIBE and bank awareness pages, not a labelled Spanish smishing corpus. — e.g., [INCIBE smishing](https://www.incibe.es/ciudadania/tematicas/ingenieria-social-fraudes-online/smishing)

### Inferences
- **F1 = 0.99 on random splits is a red flag, not a selling point.**
  - The FraudWhatsApp.Br collection used a keyword filter before labelling, so random splits probably reward keyword and template memorization.
  - The honest evaluation is **cross-source**: train on WhatsApp and test on Telegram (and vice versa), or train on IMC'25 PT/ES and test on FraudWhatsApp.Br.
  - Add near-duplicate removal (MinHash or embedding cosine > 0.95) and grouping by URL domain or template before splitting.
- **Metrics:**
  - PR-AUC, plus recall at a fixed low false-positive rate (e.g., 1%), since warning a legitimate customer is costly.
  - Per-language slices (pt-BR, pt-MZ, es if present in IMC'25).
- **Baselines:** a URL/keyword rule set (bank names, "Pix", "clique", "bloqueado") and LLM zero-shot. The learned component (multilingual-e5 + logistic regression) must beat both on the cross-source test.
- Do not use synthetic English scam dialogues as test data. At most, use them for augmentation, and flag them as synthetic.

### Gaps
- Exact sizes and licenses of FraudWhatsApp.Br and FraudTelegram.Br were not extracted; check the repo LICENSE.
- The per-language counts in IMC'25 (how many Spanish or Portuguese messages) were not found in the README. The repo has `count_lang.py`, which could produce them.
- The MOZ-Smishing license string and HF location were not verified.
- No real (non-synthetic) scam **call or dialogue** corpus in Spanish or Portuguese was found.

## Translation quality estimation for a Spanish↔Portuguese human-agent bridge

### Takeaway
Reference-free quality estimation (QE) is available off the shelf, but licensing differs:
- **CometKiwi and xCOMET are CC BY-NC-SA** (non-commercial; commercial use needs Unbabel's authorization).
- **MetricX-24 (Google) is Apache-2.0** and works reference-free. It is the safer default.

ES↔PT parallel data exists from the WMT Similar-Language Translation task (a general domain). No financial-domain ES–PT parallel corpus was verified. The credible learned component is a **QE-based "send to human review" gate**, evaluated against a small bilingual human-labelled sample.

### Cited Findings
- **Unbabel/wmt22-cometkiwi-da:**
  - License **cc-by-nc-sa-4.0**; gated behind HF login and license acknowledgment.
  - Built on InfoXLM and covers Spanish and Portuguese.
  - Outputs a score in [0, 1], where 1 means a perfect translation.
  - Usage: `pip install "unbabel-comet>=2.0.0"`. — [HF model card](https://huggingface.co/Unbabel/wmt22-cometkiwi-da)
- **XCOMET-XL:**
  - About 3.5 B parameters on XLM-R XL; detects error spans (exportable with `--to_json`).
  - License CC BY-NC-SA 4.0; "commercial use requires authorization from Unbabel". — [HF Unbabel/XCOMET-XL](https://huggingface.co/Unbabel/XCOMET-XL); [xCOMET paper](https://arxiv.org/abs/2310.10482); [COMET model licenses](https://github.com/Unbabel/COMET/blob/master/LICENSE.models.md)
- **MetricX-24:** "hybrid" models that support both reference-based and reference-free (QE) scoring. Released under **Apache-2.0** in 3 sizes on HF. — [google-research/metricx](https://github.com/google-research/metricx)
- **WMT Similar Language Translation task:**
  - Included **Spanish–Portuguese** in WMT19 and WMT20, with about 4.5 M parallel training sentences and 10.9 M Portuguese monolingual sentences.
  - Spanish, Catalan and Portuguese data were provided by Pangeanic. — [WMT19 similar](https://www.statmt.org/wmt19/similar.html); [WMT20 similar](https://www.statmt.org/wmt20/similar.html); [WMT21 similar](https://www.statmt.org/wmt21/similar.html)
- **MINDS-14 finding relevant to the bridge:** "ASR-then-translate" with Google Translate reached ≥95% intent accuracy for most languages, including ES and PT. MT therefore preserved intent well in the banking domain, though that says nothing about amounts or entities. — [Gerz et al. 2021](https://aclanthology.org/2021.emnlp-main.591.pdf)
- **Multi3NLU++:** translate-test with M2M100 performed poorly because of "repetition/nonsensical generation". Weak MT models do fail on banking text. — [arXiv 2212.10455](https://arxiv.org/html/2212.10455)

### Inferences
- **Learned component: a QE gate.** Score each LLM translation (customer PT → agent ES and back) with MetricX-24-QE or CometKiwi. Combine the score with deterministic checks in a small logistic-regression "critical-error" detector:
  - amounts and currency (R$, COP, MXN, ARS)
  - dates, card last-4 digits, IBAN/CLABE/CBU/Pix keys
  - negation ("não"/"no")
  - named entities
- **Labels:** team-generated.
  - Take about 200–300 segments from team-written bilingual banking dialogues. Include adversarial cases: swapped amounts, dropped negations, "Pix" vs "transferencia", false friends such as "exquisito" / "esquisito" and "polvo".
  - Translate them with the production LLM.
  - Have 2 bilingual annotators mark each segment OK / minor / **critical** (MQM-lite) and report Cohen's κ.
- **Baselines:** (1) no gate (always pass); (2) the rule-only number/entity check; (3) LLM self-verification.
- **Metrics:**
  - AUROC and PR-AUC for detecting critical errors.
  - Recall of critical errors at a fixed human-review budget (e.g., 10% of turns flagged).
  - Kendall τ between the QE score and human severity.
- **Split:** by dialogue (never by segment). Fit the threshold on a dev fold and report on test once.
- **Licensing:** a hackathon run by a company may be read as commercial. MetricX-24 (Apache-2.0) avoids the question. If CometKiwi or xCOMET is used, flag it as a "non-commercial research model used for evaluation only".
- **Portuñol:** add 20–30 code-mixed turns as a stress slice.

### Gaps
- No financial-domain ES↔PT parallel corpus was verified. The OPUS ECB page returned 404, so whether ECB, DGT or EUR-Lex have es–pt pairs, and their sizes, is unconfirmed.
- MetricX-24's exact language coverage and hardware needs (for Lambda/SageMaker) were not verified. The HF model-card license was confirmed only via the GitHub summary.
- No published Spanish↔Portuguese banking-dialogue QE benchmark with human labels was found.

## Small, cheap learned components for a 6-day hackathon on AWS: encoder fine-tune vs embeddings + LR vs LLM zero-shot; calibration, abstention, per-language reporting

### Takeaway
The cheapest defensible stack is **frozen multilingual sentence embeddings (multilingual-e5, MIT) + logistic regression or MLP**, optionally SetFit. Evaluate it against an **LLM zero-shot baseline** and a lexical baseline (TF-IDF + LR). Add **selective classification** (confidence threshold → human handoff) with risk–coverage curves, and report per language. Published evidence shows frozen encoders + MLP match full fine-tuning for intent detection, so XLM-R or mDeBERTa fine-tuning is optional.

### Cited Findings
- **multilingual-e5-base:**
  - License **MIT**; 12 layers, 768-dimensional; initialized from xlm-roberta-base; covers about 94–100 languages.
  - Use the "query: " prefix for classification with linear probing. Input is truncated at 512 tokens.
  - Cosine scores cluster around 0.7–1.0, so absolute similarity thresholds are not meaningful. — [HF intfloat/multilingual-e5-base](https://huggingface.co/intfloat/multilingual-e5-base)
- **Frozen encoders:** a frozen sentence encoder + MLP is "on-par with the full-model fine-tuning" for intent detection while being more efficient (citing Casanueva et al. 2020). MINDS-14 used LaBSE or mUSE with a 2-layer MLP (Adam, lr 1e-3, batch 32, 10k steps, dropout 0.3). — [Gerz et al. 2021](https://aclanthology.org/2021.emnlp-main.591.pdf)
- **SetFit:**
  - Contrastive fine-tuning of a Sentence Transformer followed by a classification head, with no prompts.
  - "Comparable results with PEFT and PET techniques, while being an order of magnitude faster to train".
  - Multilingual "by simply switching the ST body". — [Tunstall et al., arXiv 2209.11055](https://arxiv.org/abs/2209.11055)
- **Selective classification:**
  - Geifman & El-Yaniv (2017) use the softmax response as the confidence score and build selective classifiers that abstain in order to guarantee a target risk.
  - The risk–coverage curve traces coverage vs selective risk (it goes back to El-Yaniv & Wiener 2010). — [Selective Classification for DNNs](https://www.researchgate.net/publication/317100919_Selective_Classification_for_Deep_Neural_Networks); [SelectiveNet, ICML 2019](http://proceedings.mlr.press/v97/geifman19a/geifman19a.pdf)
  - Selective prediction has also been studied for NLU. — [ACL 2021](https://aclanthology.org/2021.acl-long.84.pdf)
- **Multi3NLU++ protocol:** N-fold CV (20-fold, 10-fold), micro-F1, and comparisons of XLM-R fine-tuning vs a frozen LaBSE/mpnet MLP vs QA-style mDeBERTa. It is a published template for low-data evaluation. — [arXiv 2212.10455](https://arxiv.org/html/2212.10455)

### Inferences — concrete design cards (each ≤ 2 days)

#### A. Card-workflow intent router with out-of-scope abstention (ES + PT) — **recommended primary**
- **Task:** route an ES or PT utterance to one of the workflow intents (card issue / freeze-block / abroad use / ATM limit / charge query / dispute / address change …) or **abstain → human agent**.
- **Labels and data:**
  - In-scope: MINDS-14 es-ES + pt-PT transcripts (CC-BY-4.0, human-elicited speech), mapped to the workflow intents. Optionally add Multi3NLU++ Spanish banking items (CC-BY-4.0, professionally translated) for block, lost/stolen and dispute.
  - OOS negatives: MASSIVE es-ES/pt-PT utterances (CC-BY-4.0 / Apache-2.0, human-localized) plus MINDS-14 intents held out as "unknown".
  - pt-BR slice: 100–150 team-written utterances, flagged team-generated.
- **Representations:** multilingual-e5-base embeddings ("query: " prefix) → multinomial LR. Justification: a shared ES/PT space, MIT license, CPU-cheap inference (fits Lambda), and the Gerz et al. evidence that frozen encoders suffice.
- **Baselines:**
  - (1) majority class
  - (2) TF-IDF char-n-gram + LR
  - (3) **LLM zero-shot (Bedrock) given intent descriptions** — the baseline judges will expect
- **Metrics:**
  - macro-F1 and accuracy per language (es-ES, pt-PT, pt-BR-team)
  - OOS: AUROC, FPR@95%TPR
  - selective: AURC and **accuracy at 80/90% coverage**
  - calibration: ECE (after temperature scaling on dev)
  - report the LLM's cost and latency next to the model's
- **Split and leakage:**
  - GroupKFold by utterance ID across languages (MASSIVE/Multi3NLU++ are parallel), and by speaker for MINDS-14 if available.
  - OOS *intents* held out entirely: open-set, not just OOS utterances.
  - Choose the threshold on the dev fold only; touch the test fold once.
- **Honest framing:** accuracy ceilings are high (MINDS-14 LaBSE 92–97%), so the headline should be "abstain correctly on unsupported requests at X% coverage", not accuracy.
- **Effort:** about 1–1.5 days.

#### B. Complaint (PQR/queja) product-and-issue classifier via cross-lingual transfer
- **Task:** classify complaint text into product (card / account / loan / transfer) × issue (unrecognized charge, fees, fraud, service), with labels mapped to SFC `producto`/`motivo` and consumidor.gov.br `assunto`/`problema`.
- **Labels and data:**
  - Train: CFPB narratives from the FOIA archive (English, public domain for FOIA purposes, opt-in, PII-scrubbed), optionally machine-translated to ES/PT (flag MT).
  - Test: CFPB temporal hold-out plus 100–200 team-written ES/PT complaints, dual-annotated, with κ reported.
- **Baselines:** LLM zero-shot with the taxonomy, and TF-IDF + LR on English.
- **Metrics:** macro-F1 (product), top-3 accuracy (issue), per-language, confusion on high-cost classes (fraud vs fees).
- **Leakage controls:** temporal split, deduplication of template letters, removal of company and structured fields from the input.
- **Effort:** about 1.5–2 days (data download and taxonomy mapping are the cost).
- **Risk:** the ES/PT test set is small and team-generated. State that plainly.

#### C. Scam-message risk classifier for victim support (pt-BR first)
- **Task:** decide whether a message the customer forwards (SMS or WhatsApp) is a scam, plus its scam type.
- **Labels and data:** FraudWhatsApp.Br and FraudTelegram.Br (pt-BR, 3-annotator manual labels), IMC'25 smishing (CC BY 4.0, multilingual, scam-type labels), MOZ-Smishing (pt-MZ).
- **Baselines:** keyword/URL rules and LLM zero-shot.
- **Metrics:** PR-AUC and recall@1%FPR, per source and language.
- **Split and leakage:** **cross-source** (train WhatsApp → test Telegram), near-duplicate removal, grouping by URL domain.
- **Effort:** about 1 day.
- **Caveat:** within-source F1 of 0.99 is saturated; only the cross-source numbers are meaningful.

#### D. Translation-fidelity QE gate for the ES↔PT human-agent bridge
- **Task:** flag translated turns that need human verification.
- **Labels:** about 200–300 team-annotated segment pairs (critical / minor / OK) — team-generated.
- **Model:** MetricX-24-QE (Apache-2.0) score plus number/entity/negation-mismatch features → LR.
- **Baselines:** rule-only checks, LLM self-check, and no gate.
- **Metrics:** critical-error AUROC, recall at a 10% review budget, Kendall τ.
- **Split:** by dialogue.
- **Effort:** about 1.5–2 days, most of it annotation.

#### E. (Optional) pt-BR FAQ retrieval with real relevance labels
- **Task:** match a customer question to the right answer. The BACEN FAQ question→answer pairs (CC BY 4.0) act as relevance judgments.
- **Learned vs baseline:** e5 embeddings, or a fine-tuned bi-encoder, vs BM25.
- **Metrics:** MRR@10 and Recall@k.
- **Split:** by FAQ item. Paraphrases or augmentations must stay in the same fold.
- **Effort:** about 1 day, if the dataset is actually downloadable.

### Gaps
- XLM-R and mDeBERTa-v3 licenses (believed MIT) and LaBSE's license (believed Apache-2.0) were not verified in this pass.
- No primary citation was fetched for temperature scaling or ECE (Guo et al. 2017).
- No head-to-head published numbers were found for LLM zero-shot vs e5+LR on MINDS-14 or Multi3NLU++. The team will have to produce that comparison.
- Bedrock per-call cost and latency for the zero-shot baseline were not researched here.

## Do the Factored AI & Data Hackathon 2026 rules allow external datasets / pretrained models?

### Takeaway
The public page explicitly allows any **models**, frameworks, tools and clouds. It says nothing explicit about **external datasets**. The brief's "organizer-approved data and permitted external resources" clause therefore implies getting written confirmation (hackathon.admin@factored.ai) for specific CC-BY datasets and documenting provenance per input.

### Cited Findings
- Verbatim, as returned by the page fetch: "Teams are free to use the **languages, frameworks, models, cloud platforms, and tools** they consider appropriate." (The fetch returned it as an FAQ answer beginning "Yes.") — [factored.ai AI & Data Hackathon page](https://www.factored.ai/careers/ai-data-hackathon)
- Data references on the page:
  - "Access the problem statement, dataset, Data Dictionary, Dataset Summary, and other resources"
  - "Dataset access credentials are included on the first page of the Data Dictionary."
  - Materials are in a Google Drive folder.
  - **No sentence about external/approved datasets or terms was found on the public page.** — [factored.ai](https://www.factored.ai/careers/ai-data-hackathon)
- Requirements:
  - "Your prototype should demonstrate customer-service interactions in both Spanish and Portuguese".
  - Choose one workflow: account/payment inquiries, card support, transaction disputes, or credit-product information.
  - Submission to hackathon.admin@factored.ai.
  - The challenge runs 25 Sep–5 Oct 2026, with expert evaluation 6–15 Oct and finals 15–16 Oct.
  - Evaluation dimensions are listed as headings: Technical Judgment, AI Engineering, Data Engineering, Machine Learning, Data Analytics. — [factored.ai](https://www.factored.ai/careers/ai-data-hackathon)
- Other 2026 participant repos label data provenance, e.g., "Supplied (synthetic)", and state that no organizer data or credentials are committed (secondary: search summary). — [example repo](https://github.com/Youngermaster/factored-hackathon-2026-la-brasil-del-70)

### Inferences
- Pretrained encoders (e5, XLM-R), MetricX and Bedrock LLMs are clearly permitted by the "models … tools" clause.
- External **datasets** are the grey area. The safest route is to email the organizers listing each dataset with its license (MINDS-14 CC-BY-4.0, MASSIVE CC-BY-4.0, Multi3NLU++ CC-BY-4.0, CFPB public-domain-for-FOIA, IMC'25 CC BY 4.0, FraudWhatsApp.Br). In the README, include a provenance table (real / de-identified / synthetic / team-generated / machine-translated), as the brief requires.
- **Keep organizer data out of external-model training and out of commits.** Use the synthetic dataset only for the end-to-end demo flows (card charge lookup, block, dispute), where learned labels are not needed.

### Gaps
- The problem-statement PDF and FAQ in the organizers' Google Drive were not accessible here. The exact "organizer-approved data and permitted external resources" wording and any list of approved resources could not be confirmed from a primary source.
- No separate terms-and-conditions document was linked from the public page.
