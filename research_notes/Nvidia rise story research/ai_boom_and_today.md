# Nvidia's AI Boom, 2017 to November 20, 2026: Dated Numbers and Sources

*Research cutoff: November 20, 2026 (intraday US market data). **Important late-breaking context for the writer:** In November 2026 the story took a sharp turn. Co-founder Jensen Huang resigned as CEO on Nov 12, 2026 after a scandal (affairs, one with a woman alleged to be a Chinese spy), and Nvidia's market value fell from a peak of about $5.78–5.79 trillion (Oct 6, 2026) to about $3.27–3.4 trillion (Nov 20, 2026), dropping it to the 4th most valuable US company. This happened even though it reported record results on Nov 17, 2026. Any "today" framing in the documentary must reflect this.*

---

## 1. The transformer (2017), ChatGPT (Nov 30, 2022) and how demand for Nvidia chips changed

### Takeaway
Large AI models went from being trained on about 10,000 Nvidia GPUs (GPT-3, 2020) to an estimated 25,000 (GPT-4, 2023) to 200,000 (xAI's Grok 4, 2025). After ChatGPT launched, Nvidia's May 24, 2023 sales forecast ($11 billion for one quarter, about 50% above Wall Street's estimate) was the moment investors saw the boom in Nvidia's own numbers.

### Cited Findings
- GPT-3 (OpenAI, published May 28, 2020) was trained on 10,000 GPUs, with training compute of 3.1e+23 FLOP — [Samaritan Research training-cluster dataset](https://samaritan-research.org/data-insights/training-cluster-size)
- "OpenAI ran 10,000 NVIDIA V100's for 14.8 days to train GPT-3, performing a total of 3.14*10^23 FLOP" — [LessWrong, "Estimating efficiency improvements in LLM pre-training"](https://www.lesswrong.com/posts/tJAD2LG9uweeEfjwq/estimating-efficiency-improvements-in-llm-pre-training)
- GPT-4 (Mar 15, 2023): hardware quantity listed as 25,000 (an estimate), training compute 2.1e+25 FLOP — [Samaritan Research dataset](https://samaritan-research.org/data-insights/training-cluster-size). A secondary blog says about 25,000 A100s for roughly 90–100 days — [Seifeur Guizani](https://seifeur.com/how-many-gpus-are-needed-to-train-gpt-4/) (low-quality source; treat as repeating the same estimate).
- OpenAI itself says only that it "co-designed a supercomputer from the ground up" with Azure for GPT-4, with no GPU count — [OpenAI, GPT-4 research page](https://openai.com/index/gpt-4-research/). Microsoft says GPT-4 "was trained on the Microsoft Azure AI supercomputer" — [Microsoft Research](https://www.microsoft.com/en-us/research/blog/ai-explainer-foundation-models-and-the-next-era-of-ai/)
- Later cluster sizes from the same dataset: Llama 3.1-405B (Jul 2024) 16,384 GPUs; Grok 3 (Feb 2025) 80,000; Grok 4 (Jul 9, 2025) 200,000 — [Samaritan Research dataset](https://samaritan-research.org/data-insights/training-cluster-size)
- May 24, 2023: Nvidia forecast second-quarter revenue "more than 50% above Wall Street estimates" and said it was boosting supply to meet demand for AI chips "used to power ChatGPT"; shares jumped as much as 28% after hours — [Reuters, May 24, 2023](https://www.reuters.com/technology/nvidia-forecasts-second-quarter-revenue-above-estimates-2023-05-24/)
- The next day (May 25, 2023) the stock rose 24%, adding about $184 billion and taking market value to nearly $939 billion — [Reuters via Yahoo Finance](https://finance.yahoo.com/news/nvidia-close-becoming-first-trillion-094234567.html). AP called it Nvidia "stun[ning] markets" — [AP News](https://apnews.com/article/nvidia-stock-artifical-intelligence-earnings-f6b9df3a4cafe1a4ee041cc736b97a89)
- "Since the launch of ChatGPT in 2022, Nvidia's shares have climbed 12-fold" (as of Oct 29, 2025) — [Reuters, Oct 29, 2025](https://www.reuters.com/business/nvidia-poised-record-5-trillion-market-valuation-2025-10-29/)
- In fiscal 2024 (Feb 2023–Jan 2024), Data Center revenue rose 217%. In Q4 FY24 it was up 409% year over year, "driven by higher shipments of the NVIDIA Hopper GPU computing platform used for the training and inference of large language models" — [Nvidia CFO Commentary Q4 FY24](https://s201.q4cdn.com/141608511/files/doc_financials/2024/Q4FY24/Q4FY24-CFO-Commentary.pdf)

### Inferences
- From about 10,000 GPUs (2020) to 200,000 (2025) is roughly a 20x jump in training-cluster size in five years, and each GPU generation was much more powerful than the last. The jump in compute is therefore far bigger than 20x.
- The "ChatGPT effect" on Nvidia's numbers lagged by about six months. ChatGPT launched Nov 30, 2022, and the forecast shock came May 24, 2023.

### Gaps
- The GPT-4 figure (about 25,000 A100s) is an estimate from leaked or analyst sources. OpenAI and Microsoft never confirmed it, so present it as "reportedly."
- I didn't fetch a primary source for the 2017 transformer paper ("Attention Is All You Need," Google, June 2017) or for ChatGPT's Nov 30, 2022 launch date. Both are well established but uncited here.
- I found no reliable figure for how many GPUs were used to train later OpenAI models (GPT-5, GPT-6.x).

---

## 2. The chips: A100, H100, Blackwell, Blackwell Ultra, Rubin (launch dates, prices, waiting lists)

### Takeaway
Nvidia moved from a roughly two-year chip cycle to a yearly one: A100 (2020), H100 (2022), Blackwell (2024), Blackwell Ultra (2025), Vera Rubin (shipping fall 2026). Prices rose from about $25,000–40,000 per H100 to multi-million-dollar racks, with Vera Rubin racks quoted at $5–9 million. Demand was so strong that billionaires publicly said they "begged" Jensen Huang for chips.

### Cited Findings
**Launch dates**
- A100 entered full production in May 2020; the H100 was announced in March 2022 — [Business Insider, May 2024](https://www.businessinsider.com/nvidia-jensen-huang-chips-iphone-ai-world-yearly-release-earnings-2024-5)
- H100: announced Mar 22, 2022 (GTC 2022); Nvidia began shipping Hopper H100 on Nov 16, 2022 — [WhatLedTo Nvidia roadmap timeline](https://whatledto.com/events/nvidia-datacenter-gpu-roadmap) (aggregator citing Nvidia releases)
- H200 announced Nov 13, 2023 — [WhatLedTo](https://whatledto.com/events/nvidia-datacenter-gpu-roadmap)
- Blackwell (B200, GB200) announced Mar 18, 2024 at GTC. Full production declared May 22, 2024. Shipments were reported delayed to early 2025 (Aug 5, 2024), and Nvidia disclosed a mask change to improve yields (Aug 28, 2024) — [WhatLedTo](https://whatledto.com/events/nvidia-datacenter-gpu-roadmap)
- May 2024: Huang said "after Blackwell, there's another chip. We're on a one-year rhythm" — [Business Insider](https://www.businessinsider.com/nvidia-jensen-huang-chips-iphone-ai-world-yearly-release-earnings-2024-5)
- Blackwell Ultra (B300/GB300 NVL72) announced Mar 18, 2025. Dell shipped the first GB300 NVL72 on Jul 3, 2025, and Supermicro announced volume shipments on Sep 11, 2025 — [Ancapex B300/GB300 release dates](https://www.ancapex.io/guides/b300-gb300-release-dates); [Supermicro press release, Sep 11, 2025](https://www.supermicro.com/en/pressreleases/supermicro-begins-volume-shipments-nvidia-blackwell-ultra-systems-and-rack-plug-and)
- At GTC on Mar 18, 2025, Nvidia set its roadmap: Vera Rubin in the second half of 2026, Rubin Ultra in the second half of 2027. Rubin delivers 50 petaflops of FP4, versus 20 for Blackwell — [The Verge](https://www.theverge.com/news/631835/nvidia-blackwell-ultra-ai-chip-gb300)
- Vera Rubin: on Jan 5, 2026 it was declared in full production. On Aug 27, 2026 Nvidia said production shipments began in fiscal Q3 2027. Supermicro said it was shipping Vera Rubin NVL72 racks on Sep 23, 2026 — [Ancapex](https://www.ancapex.io/guides/b300-gb300-release-dates); [WhatLedTo](https://whatledto.com/events/nvidia-datacenter-gpu-roadmap)
- Nov 17, 2026: Nvidia said it "ramped production and began shipping NVIDIA Vera Rubin NVL72 — the fastest product ramp in the company's history," with racks running at CoreWeave, Google Cloud, Microsoft Azure, Oracle Cloud Infrastructure and Nebius — [Nvidia Q3 FY27 press release](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-Third-Quarter-Fiscal-2027/default.aspx)
- Tom's Hardware headline (Nov 2026): "Vera Rubin generates $20 billion" in Q3 FY27 — [Tom's Hardware](https://www.tomshardware.com/pc-components/gpus/nvidias-revenue-hits-usd115-8-billion-as-vera-rubin-generates-usd20-billion-in-another-record-setting-quarter-commitments-increase-to-usd390-billion-fy28-forecast-raised) (not verified in the Nvidia press release, which gives no Rubin-specific revenue).

**Prices (all estimates; Nvidia does not publish list prices)**
- H100: "estimated to cost between $20,000 and $40,000 each" — [Sherwood News](https://sherwood.news/tech/hoppers-blackwells-and-rubins-a-field-guide-to-the-complicated-world-of/). As of July 2026, $25,000–40,000 depending on variant and reseller; an 8-GPU HGX H100 server costs about $250,000–320,000 — [GPUSmith pricing guide, Jul 2026](https://gpusmith.com/articles/en/nvidia-data-center-gpu-pricing-guide)
- H200: $30,000–40,000. B200: about $40,000–45,000 per GPU. HGX B200 8-GPU server about $390,000; DGX B200 about $500,000 — [GPUSmith, Jul 2026](https://gpusmith.com/articles/en/nvidia-data-center-gpu-pricing-guide)
- GB200 superchip (2 B200 GPUs + 1 Grace CPU): estimated $60,000–70,000. A full GB200 NVL72 rack (72 GPUs, 36 CPUs) is "roughly $3 million" — [Sherwood News](https://sherwood.news/tech/hoppers-blackwells-and-rubins-a-field-guide-to-the-complicated-world-of/)
- GB200 NVL72: $2.8–3.4 million. GB300 NVL72 (Blackwell Ultra, inference-optimized): $6–6.5 million. Vera Rubin NVL72: $5–7 million (including about $1 million of storage), per a Tom's Hardware source — [Tom's Hardware](https://www.tomshardware.com/tech-industry/artificial-intelligence/price-of-nvidias-vera-rubin-nvl72-racks-skyrockets-to-as-much-as-usd8-8-million-apiece-but-server-makers-margins-will-be-tight-nvidia-is-moving-closer-to-shipping-entire-full-scale-systems). The same article's headline says "as much as $8.8 million apiece."
- **Conflict:** GPUSmith puts the GB300 NVL72 at $3.7–4 million per rack — [GPUSmith](https://gpusmith.com/articles/en/nvidia-data-center-gpu-pricing-guide) — versus $6–6.5 million from Tom's Hardware's source.
- Vera Rubin NVL72 bottom-up estimate: about $9.1 million per rack, versus about $8 million "reported in the media," with the difference driven by rising HBM4 memory prices — [Plugin Capital, Jun 15, 2026](https://plugin-capital.com/2026/06/15/how-much-would-it-cost-to-build-a-gw-level-vera-rubin-data-center/)

**Shortages and "begging" stories**
- Larry Ellison (Oracle) said at Oracle's Sept 2024 analyst meeting: "In Nobu Palo Alto, I went to dinner with Elon Musk, Jensen Huang, and I would describe the dinner as me and Elon begging Jensen for GPUs. Please take our money; no, take more of it. You're not taking enough of it; we need you to take more of our money, please… It went okay; it worked." — [Tom's Hardware](https://www.tomshardware.com/tech-industry/elon-musk-and-oracle-founder-begged-nvidia-ceo-jensen-huang-for-ai-gpus-at-dinner); [Fortune, Sep 16, 2024](https://fortune.com/2024/09/16/larry-ellison-elon-musk-begged-nvidias-jensen-huang-more-gpus-fancy-sushi-dinner/)
- Motley Fool dates the remark to Oracle's financial analyst meeting on Sept 12, 2024 — [Motley Fool](https://www.fool.com/investing/2024/09/17/believe-larry-ellison-elon-musk-said-nvidia-jensen/). Business Insider calls it an "earnings call" — [Business Insider](https://www.businessinsider.com/larry-ellison-elon-musk-jensen-huang-gpus-dinner-oracle-nvidia-2024-9). Minor conflict; the analyst-meeting framing has more support.
- After the dinner, Oracle announced a supercluster of 131,072 Blackwell GPUs. At the time, xAI's Memphis supercluster had 100,000 H100s — [Tom's Hardware](https://www.tomshardware.com/tech-industry/elon-musk-and-oracle-founder-begged-nvidia-ceo-jensen-huang-for-ai-gpus-at-dinner)
- Ellison at the same meeting: building a frontier model over the next three years costs "One hundred billion… That's going to get you in the game" — [Fortune](https://fortune.com/2024/09/16/larry-ellison-elon-musk-begged-nvidias-jensen-huang-more-gpus-fancy-sushi-dinner/)
- CNBC (Nov 17, 2026): Huang "has been integral in deciding which companies got chips first" — [CNBC live blog, Nov 17, 2026](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html)

### Inferences
- A single Vera Rubin rack ($5–9 million) costs roughly as much as 150–300 H100 chips did at 2023-era prices. This is a useful "scale" visual for viewers.
- The GB300 price conflict probably reflects different configurations (training versus inference, memory and storage included or not). Present it as a range.

### Gaps
- I found no reliable A100 per-chip price (commonly cited as about $10,000–15,000, but unsourced here).
- Nvidia has never published official list prices. All prices above are analyst, reseller or industry-source estimates.
- I found no hard data on wait times in months for H100 or Blackwell (anecdotally 6–12 months in 2023, but no source fetched).

---

## 3. Revenue, Data Center share, gross margin and net income (FY2023 to Q3 FY2027)

*Note: Nvidia's fiscal year ends in late January. "Fiscal 2026" = Jan 27, 2025 to Jan 25, 2026.*

### Takeaway
Revenue went from $27.0 billion (FY2023) to $215.9 billion (FY2026), an 8x increase in three years. In the quarter ended Oct 25, 2026 (reported Nov 17, 2026), Nvidia made $115.8 billion in revenue and $65.3 billion in net profit in just three months. Data Center was about 93% of sales and gross margin was 74.8%.

### Cited Findings
**Annual (GAAP)**

| Fiscal year (ends late Jan) | Revenue | Data Center revenue | GAAP gross margin | GAAP net income | Source |
|---|---|---|---|---|---|
| FY2023 (ended Jan 29, 2023) | $26.974B | ~$15.0B (inferred, see below) | 56.9% | $4.368B | [Nvidia Q4 FY24 release](https://investor.nvidia.com/news/press-release-details/2024/NVIDIA-Announces-Financial-Results-for-Fourth-Quarter-and-Fiscal-2024/) |
| FY2024 (ended Jan 28, 2024) | $60.922B (+126%) | $47.525B | 72.7% | $29.760B (+581%) | [Nvidia Q4 FY24 release](https://investor.nvidia.com/news/press-release-details/2024/NVIDIA-Announces-Financial-Results-for-Fourth-Quarter-and-Fiscal-2024/); DC from [FY26 10-K](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000021/nvda-20260125.htm) |
| FY2025 (ended Jan 26, 2025) | $130.497B | $115.186B | 75.0% | $72.880B | [Nvidia Q4 FY26 release](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-Fourth-Quarter-and-Fiscal-2026/default.aspx); DC from [FY26 10-K](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000021/nvda-20260125.htm) |
| FY2026 (ended Jan 25, 2026) | $215.938B (+65%) | $193.737B | 71.1% | $120.067B (+65%) | [Nvidia Q4 FY26 release, Feb 25, 2026](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-Fourth-Quarter-and-Fiscal-2026/default.aspx); DC from [FY26 10-K](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000021/nvda-20260125.htm) |

- FY2026 quarterly revenue: Q1 $44.06B, Q2 $46.74B, Q3 $57.01B, Q4 $68.13B. FY26 diluted EPS was $4.90 — [Exa financials, from 10-K/10-Qs](https://exa.ai/library/organization/k21t0xmvy7z/financials?year=2026)
- FY2026 gross margin was lower (71.1% versus 75.0%) partly because of a $4.5 billion H20 China-chip charge in Q1 FY26 — [Nvidia SEC correspondence, Jul 31, 2025](https://www.sec.gov/Archives/edgar/data/1045810/000104581025000192/filename1.htm); [Q3 FY27 release footnote](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-Third-Quarter-Fiscal-2027/default.aspx)
- Q4 FY26 (ended Jan 25, 2026): revenue $68.1B (+73% year over year); Data Center $62.3B; networking $11.0B (+263%). Hyperscalers were "slightly over 50% of Data Center revenue" — [Nvidia CFO Commentary Q4 FY26](http://s201.q4cdn.com/141608511/files/doc_financials/2026/Q426/Q4FY26-CFO-Commentary.pdf)

**Most recent quarter: Q3 fiscal 2027 (ended Oct 25, 2026; reported Nov 17, 2026)**
- Revenue $115.844B, up 20% from the previous quarter and 103% from a year earlier ($57.0B in Q3 FY26) — [Nvidia press release, Nov 17, 2026](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-Third-Quarter-Fiscal-2027/default.aspx)
- Data Center revenue $107.6B (+110% year over year) — [same](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-Third-Quarter-Fiscal-2027/default.aspx). That is about 93% of sales. Hyperscalers contributed $60.1B and "AI Clouds, Industrial & Enterprise" $47.5B — [Tom's Hardware](https://www.tomshardware.com/pc-components/gpus/nvidias-revenue-hits-usd115-8-billion-as-vera-rubin-generates-usd20-billion-in-another-record-setting-quarter-commitments-increase-to-usd390-billion-fy28-forecast-raised)
- GAAP gross margin 74.8% (non-GAAP 74.9%). GAAP net income $65.287B (+105%). Diluted EPS $2.70 GAAP, $2.68 non-GAAP. Operating income $77.5B. Free cash flow $43.8B — [Nvidia press release](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-Third-Quarter-Fiscal-2027/default.aspx)
- Q2 FY27 (ended Jul 26, 2026) for comparison: revenue $96.2B, net income $59.7B, gross margin 75.0% — [same](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-Third-Quarter-Fiscal-2027/default.aspx)
- First nine months of FY27 (Jan 26 to Oct 25, 2026): revenue $293.681B and net income $183.297B, both already above all of FY2026 — [same](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-Third-Quarter-Fiscal-2027/default.aspx)
- Analysts expected $109.10B revenue and $2.48 adjusted EPS (LSEG) — [CNBC, Nov 17, 2026](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html)
- Outlook for Q4 FY27 (includes an extra week): revenue $130.0B ±3%, gross margin 71–72%, with "not assuming any Data Center compute revenue from China" — [Nvidia press release](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-Third-Quarter-Fiscal-2027/default.aspx)
- Kress raised the FY2028 growth outlook to 75% (from 70%) — [CNBC, Nov 17, 2026](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html)
- Q3 FY27 shareholder returns: $28.1B (buybacks plus dividends). The board added $150B to the buyback authorization in Sept 2026 — [Nvidia press release](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-Third-Quarter-Fiscal-2027/default.aspx)
- Note: starting Q1 FY27, Nvidia's non-GAAP figures no longer exclude stock-based compensation, so non-GAAP history was restated — [same](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-Third-Quarter-Fiscal-2027/default.aspx)

### Inferences
- Data Center share of revenue: about 78% in FY24 ($47.5B / $60.9B), about 88% in FY25, about 90% in FY26 ($193.7B / $215.9B), and about 93% in Q3 FY27. Nvidia went from a gaming-chip company to an AI-data-center company.
- FY2023 Data Center revenue was about $15.0B, inferred from FY24's $47.525B being "up 217%" (source: Q4 FY24 CFO commentary). Not directly sourced.
- If Q4 FY27 meets the $130B guidance, FY2027 revenue would be about $424B, nearly double FY2026 and about 16x FY2023. This is a projection, not a reported figure.
- Q3 FY27 net income ($65.3B in one quarter) is about 15x Nvidia's entire FY2023 net income ($4.37B).

### Gaps
- FY2023 Data Center revenue isn't directly cited (inferred above).
- FY2027 full-year results won't be reported until about late February 2027.

---

## 4. Market value milestones (1999 IPO to Nov 20, 2026)

### Takeaway
Nvidia was the first company ever to reach $4 trillion (Jul 9, 2025) and $5 trillion (Oct 29, 2025). It peaked at about $5.78–5.79 trillion on Oct 6, 2026, just short of $6 trillion, but as of Nov 20, 2026 it had lost about 41–43% of that peak (about $3.27–3.4 trillion) and fallen to 4th place among US companies.

### Cited Findings
**Contrast points (early years)**
- IPO: Jan 22, 1999 at $12 per share — [Business Today, Nov 13, 2026](https://www.businesstoday.in/latest/trends/photo/1000-in-nvidias-1999-ipo-would-be-worth-about-6-6-million-today-even-after-this-weeks-fall-567374-2026-11-13); [Motley Fool, Sep 19, 2026](https://www.fool.com/investing/2026/09/19/if-youd-invested-1000-in-nvidias-1999-ipo-heres-ho/)
- Year-end market caps: Dec 30, 2016 $57.52B; Dec 29, 2017 $117.27B; Dec 30, 2022 $359.50B; Dec 29, 2023 $1.22T; Dec 31, 2024 $3.29T; Dec 31, 2025 $4.53T — [StockAnalysis (Nasdaq Data Link)](https://stockanalysis.com/stocks/nvda/market-cap/)
- 2022 low: lowest closing price was $11.19 (split-adjusted) on Oct 14, 2022 — [StatMuse Money](https://www.statmuse.com/money/ask/nvidia-stock-lowest-price-2022)

**Milestones (first time crossed)**
- $1 trillion: May 30, 2023 — [Wikipedia, trillion-dollar companies table](https://en.wikipedia.org/wiki/list_of_public_corporations_by_market_capitalization)
- $2 trillion: Feb 23, 2024 (intraday) — [Wikipedia](https://en.wikipedia.org/wiki/list_of_public_corporations_by_market_capitalization)
- $3 trillion: Jun 5, 2024 (intraday high $1,219.93 per share, pre-split) — [Reuters, Jun 5, 2024](https://www.reuters.com/technology/nvidias-stock-market-value-hits-3-trillion-first-time-2024-06-05/)
- Most valuable listed company for the first time: Jun 18, 2024 (passed Microsoft) — [Quartz](https://qz.com/nvidia-timeline-gaming-chips-ai-giant)
- $4 trillion: Jul 9, 2025, the first company ever (briefly intraday; it closed at $3.97T) — [Reuters, Jul 9, 2025](https://www.reuters.com/world/china/nvidia-becomes-first-company-clinch-4-trillion-market-value-2025-07-09/)
- $5 trillion: Oct 29, 2025, the first company ever — [Reuters, Oct 29, 2025](https://www.reuters.com/business/nvidia-poised-record-5-trillion-market-valuation-2025-10-29/)
- All-time peak: Oct 6, 2026, share price $243.37, market cap $5,787.22B — [ET Now](https://www.etnownews.com/markets/from-5-79-trillion-to-4-32-trillion-nvidia-loses-1-47-trillion-in-market-value-since-october-peak-as-jensen-huang-probe-weighs-on-sentiment-article-156488585). Wikipedia lists the peak as $5,777B on Oct 6, 2026 — [Wikipedia](https://en.wikipedia.org/wiki/list_of_public_corporations_by_market_capitalization). Forbes says "peak at $5.7 trillion in early October, when analysts were predicting it would become the first to hit $6 trillion" — [Forbes via Yahoo, Nov 20, 2026](https://finance.yahoo.com/markets/stocks/articles/jensen-huang-lost-quarter-wealth-173124517.html)
- Nvidia "held the top spot among U.S. companies for much of the year" (2026) before the decline — [Yahoo Finance, Nov 20, 2026](https://finance.yahoo.com/markets/stocks/articles/nvidia-falls-behind-alphabet-loses-155123392.html); "As recently as last month, Nvidia held the top spot" — [Investing.com, Nov 20, 2026](https://www.investing.com/news/stock-market-news/nvidia-falls-below-alphabet-to-become-fourth-most-valuable-us-company-5042158)

**The November 2026 collapse**
- Nov 6 to Nov 9, 2026: market cap fell from $4.51T to $4.32T (–$193B, –4.3%) after the board launched an investigation into Huang — [ET Now](https://www.etnownews.com/markets/from-5-79-trillion-to-4-32-trillion-nvidia-loses-1-47-trillion-in-market-value-since-october-peak-as-jensen-huang-probe-weighs-on-sentiment-article-156488585)
- Daily market caps (Stock Alarm): Oct 30, 2026 $4.95T; Nov 4 $4.84T; Nov 5 $4.39T; Nov 12 $4.02T; Nov 17 (earnings day) $3.76T; Nov 19 $3.53T; Nov 20 $3.27T — [Stock Alarm](https://pro.stockalarm.io/quote/NVDA/metric/marketCap)
- Nov 19, 2026 close: $145.98 per share (–3.30%), market cap $3.52T, 52-week range $145.71–$243.37 — [Motley Fool quote box](https://www.fool.com/investing/2026/09/19/if-youd-invested-1000-in-nvidias-1999-ipo-heres-ho/)
- Nov 20, 2026 (intraday): Nvidia slipped behind Alphabet to become the 4th most valuable US company, "valued at $3.4 trillion," on course for a 7th straight weekly decline, "its longest losing streak since 2008." Apple was $5.08T, Microsoft $3.72T, Alphabet $3.44T (LSEG) — [Reuters via StreetInsider, Nov 20, 2026](https://www.streetinsider.com/Reuters/Nvidias+share+slide+knocks+it+below+Alphabet+in+valuation/27380111.html)
- Later on Nov 20: market cap $3.27T, down nearly 7% at 12:10 p.m. EST, below Alphabet's $3.38T — [Forbes via Yahoo](https://finance.yahoo.com/markets/stocks/articles/jensen-huang-lost-quarter-wealth-173124517.html). StockAnalysis: $3.26T, down 28% in one year — [StockAnalysis](https://stockanalysis.com/stocks/nvda/market-cap/)
- Nvidia was "down about 41% from its early October peak" and touched its lowest level since June 2025 — [Yahoo Finance](https://finance.yahoo.com/markets/stocks/articles/nvidia-falls-behind-alphabet-loses-155123392.html); [Investing.com](https://www.investing.com/news/stock-market-news/nvidia-falls-below-alphabet-to-become-fourth-most-valuable-us-company-5042158). Down more than 30% in November alone, intraday share price $140.87 — [Yicai via Sina Finance, Nov 20, 2026](https://finance.sina.com.cn/wm/2026-11-20/doc-inizmfeu7040307.shtml)
- Forward P/E fell to 10.84 (FactSet, Nov 17, 2026), "by far the lowest among the tech megacaps" — [CNBC](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html)

**Conflicts to flag**
- **$2 trillion date:** Wikipedia gives Feb 23, 2024 (intraday). Some outlets date it to the first *close* above $2T in early March 2024. I didn't verify the closing date, so say "late February 2024."
- **Peak value:** $5.7T (Forbes, rounded), $5.777T (Wikipedia), $5.787T (ET Now). Use "about $5.8 trillion, Oct 6, 2026."
- **Losing streak:** On Nov 17, CNBC said the sixth straight weekly drop was "the longest losing streak since 2012." On Nov 20, Reuters said a seventh would be "longest since 2008." Not necessarily contradictory, but check before using.
- **Nov 20 market cap** varies through the day: $3.26T, $3.27T, $3.4T and $3.52T (prior close) all appear, depending on timing.
- Some aggregator data looked unreliable and was excluded. One Coinranking table showed 2022 values from what appears to be a tokenized or synthetic product, and Business Quant showed an implausible SK hynix figure.

### Inferences
- From the Dec 30, 2022 market cap ($359.5B) to the Oct 6, 2026 peak (about $5.79T) is roughly 16x in under four years. Even after the November crash, Nov 20, 2026 ($3.27T) is still about 9x the end of 2022.
- From the Dec 30, 2016 market cap ($57.5B) to the 2026 peak is roughly 100x.
- Nvidia was valued at under $1 billion in early 1999. Stock Alarm's history chart starts at $991.76M, which suggests an IPO-era value of roughly $0.6–1B, but this is not confirmed.

### Gaps
- No precise, authoritative IPO-day market cap was found. It is commonly cited as about $600 million, but I didn't verify it.
- The exact market cap at the Oct 14, 2022 low wasn't found from a reliable source. Roughly $11.19 × about 24.6B split-adjusted shares ≈ $275B is my own estimate.
- I couldn't confirm the exact date Nvidia lost the #1 spot in October/November 2026 (it fell behind Apple first, then Microsoft, then Alphabet on Nov 20).

---

## 5. What $1,000 invested would be worth

### Takeaway
$1,000 at the 1999 IPO price would be worth roughly $4–6.6 million as of mid-November 2026, depending on method and date. Even after the November crash, the stock was up about 9x since the end of 2022.

### Cited Findings
- $1,000 at the $12 IPO price bought about 83 shares, which became 40,000 shares after six splits (2-for-1 in 2000, 2001, 2006; 3-for-2 in 2007; 4-for-1 in 2021; 10-for-1 in 2024). At $166.19 (Nov 12, 2026 close), that is about $6.65 million, excluding dividends and taxes — [Business Today, Nov 13, 2026](https://www.businesstoday.in/latest/trends/photo/1000-in-nvidias-1999-ipo-would-be-worth-about-6-6-million-today-even-after-this-weeks-fall-567374-2026-11-13)
- Bought at the first-day closing price (Jan 22, 1999) with dividends reinvested: $4,081,870 as of Nov 17, 2026 (CAGR 34.83%; the same $1,000 in the S&P 500 would be $9,584). The worst drawdown along the way was –89.72% — [What If Invest](https://what-if-invest.com/en/what-if/NVDA/1999)
- Another calculation from Jan 22, 1999 with dividends reinvested: $4,342,582 as of Nov 2026 — [Ticker Tales](https://papagong.com/blog/one-company-nvda-1999-2026/)
- Motley Fool (Sep 19, 2026): 40,000 split-adjusted shares at a split-adjusted IPO price of $0.025 were worth $5.32 million, or $5.70 million with dividends — [Motley Fool](https://www.fool.com/investing/2026/09/19/if-youd-invested-1000-in-nvidias-1999-ipo-heres-ho/)
- Why figures differ: buying at the $12 IPO price versus the first-day close (the stock jumped on day one) — [Finbold](https://finbold.com/1000-invested-in-nvidia-stock-at-ipo-is-now-worth/)

### Inferences
- At the Nov 20, 2026 intraday price of about $141, the 40,000 IPO shares would be worth about $5.6 million. Simple arithmetic, not sourced.
- Since the end of 2022, the market cap went from $359.5B (Dec 30, 2022) to $3.26T (Nov 20, 2026), about 9x, so $1,000 → about $9,000. Since the end of 2016 ($57.5B), about 57x, so $1,000 → about $57,000. These are rough, based on market cap, not total shareholder return.
- An 89.7% maximum drawdown is a strong storytelling point: early holders had to sit through a near-wipeout (around 2002 and 2008) to get the reward.

### Gaps
- I found no dedicated, sourced "$1,000 in 2016" or "$1,000 in late 2022" calculation dated November 2026. The figures above are my estimates from market-cap ratios.

---

## 6. Biggest customers, their spending, the OpenAI deal and "circular" deals

### Takeaway
A handful of buyers dominate: in FY2026, one direct customer was 22% of Nvidia's revenue and another 14%. Big Tech planned roughly $720–750 billion of 2026 capital spending across Alphabet, Amazon, Meta and Microsoft. The headline "$100 billion" Nvidia–OpenAI deal of Sept 2025 was never completed; it became a $30 billion equity stake (Feb–Mar 2026), amid growing worries about "circular" money flows.

### Cited Findings
**Customer concentration**
- FY2026: "sales to one direct customer represented 22% of total revenue and sales to another direct customer represented 14%." FY2025: 12%, 11% and 11%. FY2024: one customer at 13% — [Nvidia FY2026 10-K](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000021/nvda-20260125.htm)
- In the last three quarters (FY27), four direct customers each accounted for 11–13% of total revenue (together about 47%). Two direct customers held 18% and 17% of accounts receivable as of end-October 2026 — [CNBC, Nov 17, 2026](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html)
- Nvidia expects frontier labs (e.g., OpenAI, Anthropic) to make up about 15% of Data Center sales this year — [CNBC](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html)
- Note: "direct customers" are often server makers or distributors (e.g., ODMs), not end users. Nvidia does not name them — [Nvidia FY2026 10-K](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000021/nvda-20260125.htm)

**Big Tech spending (2026 capex guidance, as of late Oct 2026)**
- Alphabet $195–205B (maintained); Amazon $220B; Meta $135–145B (bottom raised by $5B); Microsoft lowered to $170B from $175B — [CNBC, Nov 17, 2026](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html)
- Amazon committed in Aug 2026 to buy 2 million Nvidia GPUs, a few months after ordering 1 million. Andy Jassy (Nov 17, 2026): "I don't foresee a day where we're not partners with Nvidia" — [CNBC](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html)
- Oracle: 131,072-GPU Blackwell supercluster announced Sept 2024 — [Tom's Hardware](https://www.tomshardware.com/tech-industry/elon-musk-and-oracle-founder-begged-nvidia-ceo-jensen-huang-for-ai-gpus-at-dinner)
- xAI: Memphis supercluster of 100,000 H100s (Sept 2024) — [Tom's Hardware](https://www.tomshardware.com/tech-industry/elon-musk-and-oracle-founder-begged-nvidia-ceo-jensen-huang-for-ai-gpus-at-dinner). Grok 4 was trained on 200,000 GPUs (Jul 2025) — [Samaritan Research](https://samaritan-research.org/data-insights/training-cluster-size)
- Nov 17, 2026: Meta plans expanded deployment of Vera Rubin. Vera Rubin racks are running at Microsoft Azure, Google Cloud, Oracle and CoreWeave, and "coming online soon at SpaceXSI" — [Nvidia Q3 FY27 release](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-Third-Quarter-Fiscal-2027/default.aspx)

**OpenAI and Anthropic deals**
- Sept 2025: Nvidia and OpenAI announced that Nvidia would invest up to $100B over several years, tied to deploying new data centers — [CNBC, Mar 4, 2026](https://www.cnbc.com/2026/03/04/nvidia-huang-openai-investment.html)
- Nov 2025 10-Q: the deal "may not come to fruition." WSJ (Jan 2026) said it was "on ice." The FY26 10-K (Feb 2026) said "no assurance" a transaction would be completed — [CNBC, Mar 4, 2026](https://www.cnbc.com/2026/03/04/nvidia-huang-openai-investment.html); [FY26 10-K](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000021/nvda-20260125.htm). The FT reported in Feb 2026 that the $100B deal was abandoned — [Reuters via MarketScreener, Mar 4, 2026](https://www.marketscreener.com/news/nvidia-will-not-be-able-to-invest-100-billion-in-openai-due-to-ipo-ceo-jensen-says-ce7e5fdad881ff2d)
- Feb 27, 2026: OpenAI raised $110B at an $840B valuation, with $30B from Nvidia, $50B from Amazon and $30B from SoftBank. OpenAI said it would use 5 gigawatts of Nvidia Rubin systems — [Reuters via MarketScreener, Feb 27, 2026](https://www.marketscreener.com/news/openai-s-110-billion-funding-round-draws-investment-from-amazon-nvidia-softbank-ce7e5cdfdb8aff23)
- Mar 4, 2026, Huang: "We're going to invest $30 billion in OpenAI. I think the opportunity to invest $100 billion in OpenAI is probably not in the cards," because OpenAI plans to go public. The $30B is "not tied to any deployment milestones." He said the $10B Anthropic investment "probably will be the last as well" — [CNBC, Mar 4, 2026](https://www.cnbc.com/2026/03/04/nvidia-huang-openai-investment.html); [PC Gamer](https://www.pcgamer.com/software/ai/nvidias-jensen-huang-i-think-the-opportunity-to-invest-usd100-billion-in-openai-is-probably-not-in-the-cards/)
- Anthropic went public on Nasdaq on Nov 19, 2026, opening at $111.50 (34% above its IPO price). Nvidia holds a sizable stake and invested more at the IPO price — [Forbes via Yahoo](https://finance.yahoo.com/markets/stocks/articles/jensen-huang-lost-quarter-wealth-173124517.html); [CNBC](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html)

**"Circular" deal concerns and guarantees**
- Bloomberg: "The risk with these 'circular' deals is that they can create skewed incentives that may lead to bad decision making and magnify losses if demand for AI fails to match today's lofty expectations" — [Bloomberg graphic, 2026](https://www.bloomberg.com/graphics/2026-ai-circular-deals/)
- Reuters (Feb 27, 2026): the OpenAI round "exacerbates Wall Street concerns about 'circular' financing agreements, where firms invest in and sign supply deals with each other, inflating demand and revenue" — [Reuters via MarketScreener](https://www.marketscreener.com/news/openai-s-110-billion-funding-round-draws-investment-from-amazon-nvidia-softbank-ce7e5cdfdb8aff23)
- As of Oct 25, 2026, Nvidia had $118B in guarantees (land, power, shell and hardware financing), notably for an OpenAI project in Ohio. Maximum exposure is $105B, and Nvidia says it "ha[s] not made any payments" so far. It also has $32B of neocloud commitments through 2032 and $102B of data center lease and cloud service commitments (up from $74B) — [CNBC, Nov 17, 2026](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html)
- Supply commitments rose to $390B from $279B, mainly multi-year memory procurement — [Tom's Hardware headline](https://www.tomshardware.com/pc-components/gpus/nvidias-revenue-hits-usd115-8-billion-as-vera-rubin-generates-usd20-billion-in-another-record-setting-quarter-commitments-increase-to-usd390-billion-fy28-forecast-raised). CNBC's text says "$390 million," which is almost certainly a typo for $390 billion — [CNBC](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html)
- Kress (Nov 17, 2026): Nvidia will be "rigorously evaluating future investments, commitments, and guarantees" — [CNBC](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html)
- Other 2026 deals: agreement to acquire Hugging Face for "just under $13 billion" (Sept 2026, pending), and a $2.944B payment related to Groq, Inc. in FY27 — [CNBC](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html); [Q3 FY27 cash flow statement](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-Third-Quarter-Fiscal-2027/default.aspx)

### Inferences
- The four hyperscalers' 2026 capex guidance adds up to roughly $720–750B (sum of the ranges above). Not all of it goes to Nvidia, since it also covers buildings, power, networking and their own chips.
- Nvidia is now both a supplier and a financier, through equity stakes, lease guarantees and neocloud backstops. That is the core of the "circular" critique.

### Gaps
- Nvidia doesn't name its top customers, so I found no authoritative per-company spending on Nvidia chips (e.g., "Microsoft spent $X on Nvidia in 2026").
- Microsoft's capex figure may refer to its fiscal year (July–June). CNBC said "for the year" without clarifying.
- I didn't research xAI's or Oracle's 2026 spending specifically.

---

## 7. Headwinds: China export controls, the DeepSeek shock, AI-bubble worries, in-house chips, and the Huang scandal

### Takeaway
Nvidia has faced repeated shocks. The DeepSeek selloff on Jan 27, 2025 wiped out about $589–593 billion in one day, a record. China export rules cut off a market Huang called worth $50 billion. In November 2026 the CEO's resignation, a spy-linked scandal, tighter US rules on Chinese remote access to chips and broad AI-spending fears together erased more than $2 trillion of value from the October peak.

### Cited Findings
**DeepSeek (Jan 27, 2025)**
- Nvidia fell 17%, "evaporating $593 billion of the chipmaker's market value, a record one-day loss for any company on Wall Street" — [Reuters, Jan 27, 2025](https://www.reuters.com/technology/chinas-deepseek-sets-off-ai-market-rout-2025-01-27/)
- Bloomberg's figure: $589 billion, "Largest in Market History," beating the previous record (about $279B in Sept 2024, also Nvidia). "Nvidia is responsible for 8 of 10 largest market value drops" — [Bloomberg, Jan 27, 2025](https://www.bloomberg.com/news/articles/2025-01-27/asml-sinks-as-china-ai-startup-triggers-panic-in-tech-stocks)
- Nvidia rebounded 8.9% the next day (Jan 28, 2025) — [Reuters, Jan 28, 2025](https://www.reuters.com/technology/tech-stock-selloff-deepens-deepseek-triggers-ai-rethink-2025-01-28/)
- **Conflict:** $593B (Reuters) versus $589B (Bloomberg). Both describe the same day; the difference comes from share-count and price methodology. Say "nearly $600 billion."

**China export controls**
- Export controls on advanced chips were defined in Oct 2023. Nvidia designed the H20 specifically for China to comply — [Nvidia SEC correspondence, Jul 31, 2025](https://www.sec.gov/Archives/edgar/data/1045810/000104581025000192/filename1.htm)
- Apr 9, 2025: the US government required a license to export the H20 to China. On Apr 14 it said the requirement was "for the indefinite future." Nvidia initially expected up to about $5.5B in charges — [Nvidia 8-K, Apr 15, 2025](https://www.sec.gov/Archives/edgar/data/1045810/000104581025000082/nvda-20250409.htm)
- The actual Q1 FY26 charge was $4.5B. Nvidia also couldn't ship $2.5B of H20 revenue in Q1 and expected an $8B hit in Q2. Huang: "the $50 billion China market is effectively closed to us" — [TechCrunch, May 28, 2025](https://techcrunch.com/2025/05/28/nvidia-expects-to-lose-billions-in-revenue-due-to-h20-chip-licensing-requirements/)
- Jul 2025: the US reversed the April ban (Lutnick: "We put that in the trade deal with the magnets") — [Reuters, Jul 15, 2025](https://www.reuters.com/technology/nvidia-resume-h20-gpu-sales-china-2025-07-15/). Licenses started being issued on Aug 8, 2025 — [Reuters, Aug 8, 2025](https://www.reuters.com/world/china/us-licenses-nvidia-export-chips-china-official-says-2025-08-08/)
- Nov 16, 2026: the Commerce Department's Bureau of Industry and Security issued an interim rule requiring data center operators in countries including Singapore, Indonesia, Malaysia and Thailand to get a license, closing a loophole that let Chinese companies rent Nvidia computing power abroad. China said it "firmly opposes" the rule and threatened countermeasures — [CNBC, Nov 17, 2026](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html)
- Short-seller Culper Research alleges 20% of Nvidia's FY2026 compute revenue was "driven by China." Nvidia denies any physical diversion — [CNBC](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html) (a short seller's claim; treat with caution)

**The Jensen Huang scandal (Nov 2026)**
- Nov 8, 2026: Huang admitted an extramarital affair — [CNBC](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html). The New York Times then reported a second affair, with Nvidia VP of healthcare Kimberly Powell — [Fortune, Nov 12, 2026](https://fortune.com/2026/11/12/ceo-jensen-huang-net-worth-drops-10-billion-nvidia-stock-slides-fallout-affair-scandals-company-exec-alleged-spy/)
- Nov 12, 2026: Huang resigned as president, CEO and board member, effective immediately. CFO Colette Kress became interim CEO — [Fortune](https://fortune.com/2026/11/12/ceo-jensen-huang-net-worth-drops-10-billion-nvidia-stock-slides-fallout-affair-scandals-company-exec-alleged-spy/); [MythPost](https://www.mythpost.com/money-deals/jensen-huang-net-worth-2026/)
- Board chair Harvey Jones (on the board since 1993; now its first-ever chair) said Huang resigned after disclosing behavior "inconsistent with the company's code of conduct" and "the Nvidia board unanimously accepted his resignation and does not intend to reinstate Jensen as CEO." Heidrick & Struggles is running the CEO search, and Wachtell Lipton is leading the probe into whether national security or company secrets were compromised — [CNBC](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html)
- The woman, Alice Huang, once led Singapore-based Megaspeed, an Nvidia partner. The DOJ and Commerce confirmed on Nov 16, 2026 that they have investigated Megaspeed for export violations since 2024. Nvidia put Megaspeed on its "no sell" list in June 2025 — [CNBC](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html)
- Huang (Nov 17, 2026): he made "serious mistakes" and would be "honored" to return if the board decided it was best. Elon Musk and others called for his return, and President Trump said he would be open to it — [CNBC](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html)
- Huang and General Counsel Tim Teter are due before US congressional committees in early December 2026 — [Investing.com](https://www.investing.com/news/stock-market-news/nvidia-falls-below-alphabet-to-become-fourth-most-valuable-us-company-5042158)
- Nov 17, 2026: the board created a committee on national security and export controls — [CNBC](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html)
- Morgan Stanley cut its calendar 2027–2028 Data Center estimates by about 10% on the Huang news. More than 20 analysts cut price targets within nine days — [CNBC](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html)

**AI-bubble worries and in-house chips**
- AI stocks had "a rough October [2026] thanks to a series of poor earnings where high capital expenditures spooked investors," fears worsened after Democrats won the House and Senate in the midterms, and Anthropic's Nov 19 debut "failed to ease broader concerns about substantial infrastructure spending" — [Forbes via Yahoo, Nov 20, 2026](https://finance.yahoo.com/markets/stocks/articles/jensen-huang-lost-quarter-wealth-173124517.html)
- Reuters (Nov 20, 2026): investors are moving toward "companies that pair heavy AI investment with established cloud and software revenue streams" — [Reuters via StreetInsider](https://www.streetinsider.com/Reuters/Nvidias+share+slide+knocks+it+below+Alphabet+in+valuation/27380111.html)
- Amazon's Trainium chips are "designed to be a direct competitor to Nvidia's popular Blackwell," and Amazon plans to sell Trainium externally from "late 2027" — [CNBC](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html)
- Anthropic's IPO prospectus names Nvidia, AMD, Google and Amazon as its chip providers — [CNBC](https://www.cnbc.com/2026/11/17/nvidia-nvda-earnings-report-q3-2027.html). AMD passed a $1 trillion market cap for the first time on Sep 21, 2026 — [Wikipedia](https://en.wikipedia.org/wiki/list_of_public_corporations_by_market_capitalization)

### Inferences
- The November 2026 drop ($5.79T peak on Oct 6 to $3.27T on Nov 20, about –$2.5T) is far bigger in total than DeepSeek but spread over weeks, not one day. The largest single-day drop in the daily data I saw was Nov 4 to Nov 5, 2026 (about –$448B, from $4.84T to $4.39T per Stock Alarm), so the DeepSeek one-day record ($589–593B) appears to still stand. I haven't verified this for every trading day since Jan 2025.
- The story arc for the film: record business results (Nov 17) collided with leadership, geopolitical and AI-spending fears, and the stock went down despite the earnings.

### Gaps
- I didn't fully trace the Jan 2026 H200 China export policy (case-by-case review). A search summary mentioned it, but I didn't confirm it from a primary source.
- I didn't research Google TPU, Meta MTIA or Microsoft Maia custom-chip volumes in 2026.
- I couldn't confirm that the DeepSeek day remains the all-time record as of Nov 20, 2026 (see inference above).
- The allegation that Alice Huang is a Chinese spy is reported as "alleged," based on reports of US intelligence views. It must be presented as an allegation.

---

## 8. Employees, value per employee and Jensen Huang's net worth

### Takeaway
Nvidia had about 42,000 employees (Jan 25, 2026), up from 26,196 in Jan 2023 and 10,299 in Jan 2017. At the Oct 2026 peak that was roughly $138 million of market value per employee; at Nov 20, 2026 it is about $78 million. Jensen Huang's net worth fell from about $204.5 billion (Forbes, Oct 2, 2026) to about $119–127.5 billion (Nov 20, 2026).

### Cited Findings
**Employees (from 10-K filings)**
- FY2026 (as of Jan 25, 2026): about 42,000 employees in 38 countries, of whom 31,000 in R&D and 11,000 in sales, marketing, operations and administration. Turnover rate was 3.7% — [Nvidia FY2026 10-K](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000021/nvda-20260125.htm)
- 6,000 new hires in FY26; turnover of 3.7% versus a tech industry average of 21.9% — [Nvidia Sustainability Report FY2026](https://images.nvidia.com/aem-dam/Solutions/documents/NVIDIA-Sustainability-Report-Fiscal-Year-2026.pdf)
- History: Jan 2017: 10,299. Jan 2018: 11,528. Jan 2020: 13,775. Jan 2023: 26,196. Jan 2024: about 29,600. Jan 2025: about 36,000. Jan 2026: about 42,000 — [Steadybase, quoting each 10-K](https://steadybase.io/company/nvidia-corporation/employees/); [Bebop](https://bebop.ai/companies/nvidia-employees)

**Jensen Huang's net worth**
- Forbes real-time: $127.5B, #14 in the world (as of Nov 20, 2026) — [Forbes profile](https://www.forbes.com/profile/jensen-huang/)
- Forbes article: $119B at 12:10 p.m. EST on Nov 20, 2026 (#15), down about $43.2B (26.6%) since Nov 9 — [Forbes via Yahoo, Nov 20, 2026](https://finance.yahoo.com/markets/stocks/articles/jensen-huang-lost-quarter-wealth-173124517.html)
- Bloomberg Billionaires Index: $122B, #16, down $40.1B (–24.8%) year over year. Public assets $118.5B in Nvidia stock, $3.43B cash — [Bloomberg](https://www.bloomberg.com/billionaires/profiles/jenhsun-huang/)
- Forbes estimate on Oct 2, 2026: $204.5B — [MythPost, citing Forbes](https://www.mythpost.com/money-deals/jensen-huang-net-worth-2026/) (secondary source)
- Stake: about 870 million shares (about 3.5%) per a Sept 2026 filing — [Fortune, Nov 12, 2026](https://fortune.com/2026/11/12/ceo-jensen-huang-net-worth-drops-10-billion-nvidia-stock-slides-fallout-affair-scandals-company-exec-alleged-spy/). 870,604,104 shares (3.58%) per the Mar 23, 2026 proxy, and he forfeits about $108M of unvested awards — [MythPost](https://www.mythpost.com/money-deals/jensen-huang-net-worth-2026/)
- On Nov 12, 2026 (resignation day): $145B and 13th richest — [Fortune](https://fortune.com/2026/11/12/ceo-jensen-huang-net-worth-drops-10-billion-nvidia-stock-slides-fallout-affair-scandals-company-exec-alleged-spy/)

### Inferences
- Market value per employee: about $138M at the Oct 6, 2026 peak ($5.79T / 42,000), and about $78M at Nov 20, 2026 ($3.27T / 42,000). Headcount is as of Jan 2026 and the true Nov 2026 headcount is likely higher, so these per-employee figures are slight overestimates.
- Revenue per employee in FY2026: about $5.1M ($215.9B / 42,000).
- Headcount roughly 4x since 2017 (10,299 to 42,000), while market value rose about 28–50x (end-2017 $117B to $3.3–5.8T). This is a strong illustration of how lean Nvidia is relative to its value.

### Gaps
- No headcount figure for November 2026. The next official count comes in the FY2027 10-K (about late Feb 2027).
- Net worth figures move by billions daily, and Forbes ($119–127.5B) and Bloomberg ($122B) differ on Nov 20, 2026. Present it as "around $120 billion as of Nov 20, 2026."
- The Oct 2, 2026 Forbes figure ($204.5B) comes via a secondary site, and I didn't verify it directly on Forbes.
