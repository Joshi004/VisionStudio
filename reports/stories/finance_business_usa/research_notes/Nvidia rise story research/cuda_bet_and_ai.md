# Nvidia's CUDA Bet and How GPUs Became the Engine of AI (c. 2003–2017)

Research notes for a storytelling documentary. Researched November 20, 2026. Every claim has an inline source; conflicts and weak sources are flagged with **⚠**.

---

## 1. What was GPGPU? Ian Buck, Stanford's Brook, and science on gaming cards before CUDA

### Takeaway
"GPGPU" (general-purpose computing on GPUs) was the early-2000s hack of tricking gaming graphics chips into doing math by pretending the numbers were pixels. It took "a PhD in computer graphics" to do it. Ian Buck's Stanford "Brook" language made it programmable like ordinary C. Nvidia then hired Buck to build CUDA. Medical imaging (CT scan reconstruction) researchers were among those already using graphics hardware before CUDA.

### Cited Findings
**The GPGPU idea and why it was hard**
- Buck's PhD thesis (Stanford, advisor Pat Hanrahan) noted GPUs had "peak performance of over 60 GFLOPS" that "dwarfs that of today's commodity CPU at a price of only a few hundred dollars". But graphics APIs forced programmers to think in "textures, triangles, and pixels", which led to "difficult and often unmanageable programming approaches." — [Buck thesis, "Stream Computing on Graphics Hardware"](https://graphics.stanford.edu/~ianbuck/thesis.pdf)
- Buck: "At the time, it required a PhD in computer graphics to be able to port an application to the GPU. So I started the Brook project with the goal of defining a programming language for GPU computing, which abstracted the graphics-isms of the GPU into more general programming concepts." Brook's core concept was the "stream," a collection of data elements needing similar work. — [Tom's Hardware interview with Ian Buck](https://www.tomshardware.com/reviews/ian-buck-nvidia,2393.html)
- Buck on the origins in game graphics: shader programs "were tiny then—four instructions, maybe eight—but they were running on every pixel on the screen; a million pixels, sixty times per second. This was essentially a massively parallel program to try to make beautiful games, but we started by seeing a fit for matrix multiplies and linear algebra." — [NVIDIA Technical Blog (quoting The Platform)](https://developer.nvidia.com/blog/inside-the-programming-evolution-of-gpu-computing/)
- Buck said GPUs were following "a Moore's law cubed performance growth rate, way faster than the CPU." He also experimented with fluid simulation on graphics hardware (SGI O2) at Princeton. — [Tom's Hardware](https://www.tomshardware.com/reviews/ian-buck-nvidia,2393.html)
- Brook (BrookGPU) compiled C-like code to both NVIDIA and ATI hardware via OpenGL/DirectX. Collaborators were Tim Foley, Jeremy Sugerman and Daniel Horn. — [Ian Buck résumé, Stanford](https://graphics.stanford.edu/~ianbuck/resumeWeb.html)
- The gpgpu.org community dates GPU computing history "back to 2002." — [Tom's Hardware](https://www.tomshardware.com/reviews/ian-buck-nvidia,2393.html)

**Ian Buck's colorful backstory (good for storytelling)**
- In 2000, as a Stanford grad student, Buck "chained thirty-two GeForce cards together to play Quake using eight projectors." Buck: "It was the first gaming rig in 8K resolution, and it took up an entire wall… It was beautiful." — [The New Yorker, Stephen Witt, Nov 27, 2023](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
- "With a grant from DARPA… Buck hacked the shaders to access the parallel-computing circuits below, repurposing the GeForce into a low-budget supercomputer. Soon, Buck was working for Huang." — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
- Buck had an earlier stint at NVIDIA as a systems engineer (Nov 2000–Sep 2001) and a Microsoft Research internship (2003) doing GPU handwriting/speech recognition. — [Buck résumé](https://graphics.stanford.edu/~ianbuck/resumeWeb.html)

**How Nvidia hired him**
- Buck: "I started CUDA while completing my research at Stanford. Nvidia was already very supportive of my research… I joined Nvidia to start the CUDA project in 2005. At the time, it was just myself and one other engineer." — [Tom's Hardware](https://www.tomshardware.com/reviews/ian-buck-nvidia,2393.html)
- **⚠ Date conflict:** The New Yorker says "Since 2004, Buck has overseen the development of… CUDA" ([New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)). NVIDIA's blog says interest grew "after 2004, when Buck took the work to NVIDIA" ([NVIDIA blog](https://developer.nvidia.com/blog/inside-the-programming-evolution-of-gpu-computing/)). Buck himself says he joined in 2005 ([Tom's Hardware](https://www.tomshardware.com/reviews/ian-buck-nvidia,2393.html)). The Register (Dec 2011) says NVIDIA "brought Buck aboard six years ago", which also points to about 2005 ([The Register](https://www.theregister.com/off-prem/2011/12/12/meet-the-boffin-who-gave-gpus-a-bigger-bang-for-the-buck/1089412)). Safest wording: "around 2004–2005."
- Buck said CUDA dropped Brook's restrictive memory model: "the programmer was simply given a massive pool of threads and could access memory any way he or she wished… [allowing] full C language semantics on the GPU." — [Tom's Hardware](https://www.tomshardware.com/reviews/ian-buck-nvidia,2393.html)

**Science on graphics cards before CUDA**
- Medical CT scans: Cabral et al. (1994) used SGI workstation texture hardware to speed up CT reconstruction. Mueller & Yagel (2000) used OpenGL for iterative CT reconstruction. In 2004, "cheap commodity PC graphics hardware could be used instead of an expensive SGI system" (Xu & Mueller, 2004). — [Eklund et al., "Medical Image Processing on the GPU: Past, Present and Future"](https://www.diva-portal.org/smash/get/diva2:625940/FULLTEXT02)
- Chidlow & Möller (2003) ran emission tomography (OS-EM) on a consumer Nvidia GeForce 4 card. A later GPU CT solution met streaming-CT requirements "on a graphics board available at a price of less than $500," whereas a dual-Pentium PC took 60–100 seconds per 512³ reconstruction. — [Xu & Mueller, "Real-time 3D CT reconstruction using commodity graphics hardware"](https://www3.cs.stonybrook.edu/~mueller/papers/pmb7_12_006.pdf)
- The same review found GPU-accelerated image registration "became much more common in 2008, after the release of CUDA in 2007." — [Eklund et al.](https://www.diva-portal.org/smash/get/diva2:625940/FULLTEXT02)
- Physics: National Taiwan University physicist Ting-Wai Chiu built a homemade GeForce supercomputer to simulate matter after the Big Bang. Huang found "the lab littered with GeForce boxes and the computer cooled by oscillating desk fans." Chiu: "Jensen is a visionary… He made my life's work possible." (This was CUDA-era, cited by Huang as a confidence boost in the dark years.) — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
- UIUC's Theoretical and Computational Biophysics Group (Klaus Schulten) was "one of the first research groups to leverage the parallel architecture of the GPU," accelerating the NAMD/VMD molecular dynamics software. — [NVIDIA/UIUC press release, June 30, 2008](https://www.ks.uiuc.edu/Publications/pdfs/2008-06-30-nvidia.com-NVIDIA_Appoints_First_CUDA_Center_of_Excellence.pdf)

### Inferences
- The story structure is that the hardware was already there (gamers were buying it), but only graphics wizards could use it. CUDA's breakthrough was making it usable by ordinary C programmers and scientists.
- The New Yorker's "32 GeForce cards playing Quake on a wall" anecdote is a vivid, visual opening for the Buck segment.

### Gaps
- I didn't find who at Nvidia recruited Buck (e.g., David Kirk or Huang personally) or the terms of the hire.
- I didn't find a well-sourced pre-CUDA physics example on gaming cards. Chiu's work appears to be CUDA-era. Folding@home's 2006 GPU client (on ATI cards) is often cited but was not verified here.

---

## 2. CUDA's launch, what it let people do, why it went into every chip, and what it cost

### Takeaway
Nvidia unveiled CUDA on Nov 8, 2006 with the GeForce 8800 (G80). A public SDK followed in Feb 2007 and version 1.0 in June 2007. In plain terms, any C programmer could now turn a $500 gaming card into a small supercomputer. Huang put CUDA on every GeForce to build an "install base." By his own account, this raised chip cost about 50% for a roughly 35%-gross-margin company and "consumed all of the company's gross profit dollars." **The popular "$500 million per year on CUDA" figure is not verified.** Book summaries instead attribute about $475–500M to developing the G80 chip over four years. Nvidia's total R&D was $554M–$909M per year in FY2007–FY2010.

### Cited Findings
**Launch dates**
- Nov 8, 2006: NVIDIA "unveiled NVIDIA CUDA technology, a fundamentally new architecture for computing on… GPUs, and the industry's first C-compiler development environment for the GPU." The release claimed "hundreds of on-chip processor cores" solving problems "up to 100 times faster than traditional approaches." It was available "on the new GeForce® 8800 graphics card." — [NVIDIA press release, Nov 8, 2006 (archived)](https://web.archive.org/web/20200703112618/http:/www.nvidia.com/object/IO_37226.html)
- Feb 16, 2007: public beta of the CUDA SDK and C compiler, "now available to all developers." Target uses included "seismic processing for oil and gas exploration, computing in bioscience, and financial modeling." — [NVIDIA press release via WebWire](https://www.webwire.com/ViewPressRel.asp?aId=27584)
- June 2007: CUDA Toolkit/SDK 1.0 released, with the CUBLAS and CUFFT math libraries. — [NVIDIA Developer Forums, Jun 26, 2007](https://forums.developer.nvidia.com/t/cuda-1-0-released/982); [CUDA Programming Guide 1.0](https://developer.download.nvidia.com/compute/cuda/1.0/NVIDIA_CUDA_Programming_Guide_1.0.pdf)
- CUDA = "Compute Unified Device Architecture… for issuing and managing computations on the GPU… without the need of mapping them to a graphics API." — [CUDA Programming Guide 1.0](https://developer.download.nvidia.com/compute/cuda/1.0/NVIDIA_CUDA_Programming_Guide_1.0.pdf)
- NVIDIA's own retrospective: announced Nov 2006 and "brought it to the scientific community at SC06." — [NVIDIA Blog, "CUDA at 20"](https://blogs.nvidia.com/blog/20-years-cuda/)
- **⚠ "2006 vs 2007":** Both are defensible. Announced and shipped on GeForce 8800 in Nov 2006, public SDK in Feb 2007, v1.0 in June 2007. Some summaries say "introduced in 2007" ([BFS Invest summary of The Nvidia Way](https://www.bfsinvest.com/nvidias-jensen-huang-the-ultimate-entrepreneur)).

**What it let people do (plain terms)**
- Stephen Witt: "you took your graphics card, you installed CUDA, and it was like you flipped the switch on the graphics card and it turned from being a video game component into a low-budget supercomputer. And they put this software on every card that they shipped." — [Front Row Podcast with Stephen Witt (transcript)](https://www.ykeith.com/p/witt)
- Nvidia marketed CUDA to "stock traders, oil prospectors, and molecular biologists," and even signed a deal with General Mills "to simulate the thermal physics of cooking frozen pizza." AI was not a focus: "There didn't seem to be much of a market." — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)

**Why CUDA went into every chip, including cheap gaming cards**
- Huang: "Huang's vision was to enable CUDA to work on every GeForce card. 'We were democratizing supercomputing.'" — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
- Huang (Lex Fridman Podcast #494): "we wanted to be a computing company. A computing company has a computing architecture. A computing architecture has to be compatible across all of the chips that we build." He added: "Install base defines an architecture… Everything else is secondary." Nvidia would "put CUDA on GeForce and put it into every single PC, whether customers use it or not… Meanwhile, we'll go and attract developers." — [Lex Fridman Podcast #494 transcript](https://lexfridman.podhood.com/eca4cb06-5e04-43fd-b967-6fa4eea152cf)
- Huang: "NVIDIA is the house that GeForce built because it was GeForce that took CUDA out to everybody. Researchers, scientists… many of them were gamers." — [Lex Fridman #494](https://lexfridman.podhood.com/eca4cb06-5e04-43fd-b967-6fa4eea152cf)
- Huang called it "the first strategic decision that… is as close to an existential threat." — [Lex Fridman #494](https://lexfridman.podhood.com/eca4cb06-5e04-43fd-b967-6fa4eea152cf)
- Nvidia's hardware team "began allocating space on the microchips for supercomputing operations." Lead chip engineer Arjun Prabhu compared chip design to "urban planning, with different zones of the chip dedicated to different tasks." — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
- Huang's "zero-billion-dollar market" concept describes exploratory products "such as CUDA, which not only do not have competitors but don't even have obvious customers." — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)

**What it cost**
- Huang's own numbers: "we increased our cost by fifty percent… and we were a thirty-five percent gross margin company… the management team knew our gross margins were gonna get crushed… GeForce would carry the burden of CUDA, and none of the gamers would appreciate it, and none of the gamers would pay for it." It "completely consumed all of the company's gross profit dollars" and "it took a decade." — [Lex Fridman #494](https://lexfridman.podhood.com/eca4cb06-5e04-43fd-b967-6fa4eea152cf)
- G80 development cost: "Nvidia spent $475 million developing the G80 as a GPU computing chip, and also spent heavily to make its GPUs compatible with CUDA." — [getAbstract review of Tae Kim's *The Nvidia Way*](https://journal.getabstract.com/en/review/the-nvidia-saga/). Another summary of the same book: "It took four years and almost $500 million in R&D expense to create the G80 chip." — [BFS Invest summary of *The Nvidia Way*](https://www.bfsinvest.com/nvidias-jensen-huang-the-ultimate-entrepreneur)
- Nvidia's actual total R&D spend (all projects, not CUDA-only) from SEC 10-Ks: **FY2007 $553.5M; FY2008 $691.6M; FY2009 $855.9M; FY2010 $908.9M; FY2011 $848.8M.** R&D headcount grew from 2,668 (Jan 2007) to 3,772 (Jan 2009). — [NVIDIA FY2009 10-K](https://www.sec.gov/Archives/edgar/data/1045810/000104581009000013/fy2009form10k.htm); [FY2010 10-K](https://www.sec.gov/Archives/edgar/data/1045810/000104581010000006/0001045810-10-000006.txt); [FY2011 10-K](https://www.sec.gov/Archives/edgar/data/1045810/000104581011000015/0001045810-11-000015.txt)
- Ben Gilbert (Acquired): "They were spending many billions targeting an obscure corner of academic and scientific computing, which was not a large market at the time—certainly less than the billions they were pouring in." — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
- **⚠ "$500M per year on CUDA" is unverified.** The only source I found saying "about $500 million a year, or 15 to 20 percent of revenue" is a low-quality biography site that also wrongly calls Buck a "Stanford professor" ([hub.cissychen.com](https://hub.cissychen.com/biographies/huang-day6.en.html)). Don't use it. The ~$500M figure most likely refers to the G80's total development cost (above), or it conflates Nvidia's total annual R&D, which was larger than $500M.
- **⚠ Transistor overhead:** The same low-quality site claims CUDA added "roughly twenty percent more transistor area per die." That is unverified; don't use it. Huang's own on-record figure is "+50% cost."

### Inferences
- Computed from the 10-K tables (my arithmetic, not a quoted figure): gross margin was about 45.6% in FY2008 ($1.87B gross profit on $4.10B revenue). It fell to about 34.3% in FY2009 ($1.17B on $3.42B), which includes the $196M laptop-chip charge. Huang's "35% gross margin company" lines up with the FY2009 trough rather than the pre-CUDA era, so treat his framing as approximate memory.
- The documentary can frame the cost as a hidden tax that every gamer's card carried for a feature almost no gamer used.

### Gaps
- Nvidia never broke out CUDA-specific spending in its filings, so no audited "cost of CUDA" exists.
- I did not obtain direct text from *The Nvidia Way* or *The Thinking Machine* on cost. Figures above come from third-party summaries.
- I didn't fetch Acquired or Stratechery episodes directly. The Gilbert quote is via the New Yorker.

---

## 3. How investors reacted: the stock collapse, criticism, and the 2008 laptop-chip write-off

### Takeaway
Wall Street "reacted with dismay." By the end of 2008, Nvidia's stock was down about 70–77%, and market cap fell from about $19B (end-2007) to about $3.5–4B (Nov–Dec 2008). Three things hit at once: the financial crisis, a profit warning, and a $196M charge for defective laptop chips. CUDA downloads peaked in 2009 and then fell for three years. As late as 2013, an activist hedge fund (Starboard) circled, and the board feared pressure to cut CUDA.

### Cited Findings
**Wall Street's view of CUDA**
- "When CUDA was released, in late 2006, Wall Street reacted with dismay. Huang was bringing supercomputing to the masses, but the masses had shown no indication that they wanted such a thing… by the end of 2008 Nvidia's stock price had declined by seventy per cent." — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
- "Downloads of CUDA hit a peak in 2009, then declined for three years. Board members worried that Nvidia's depressed stock price would make it a target for corporate raiders." Board member Jim Gaither: "We did everything we could to protect the company against an activist shareholder who might come in and try to break it up." Dawn Hudson (joined 2013): "It was a distinctly flat, stagnant company." — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
- 2013 activist episode: Starboard Value built a stake of 4.4M shares (about $62M) in the quarter ending June 2013, when Nvidia's total market value was about $8B with about $3B net cash. "The company's board was very worried that the activist fund would force a reorganization… and make Nvidia cut back on its investments in CUDA." Starboard pushed for buybacks; Nvidia announced $1B+ in buybacks in Nov 2013, and Starboard exited by March 2014. — [CNBC excerpt from Tae Kim's *The Nvidia Way*, Dec 5, 2024](https://www.cnbc.com/2024/12/05/nvidia-and-starboard-value-excerpt-from-tae-kims-book-on-nvidia.html)

**The July 2008 warning and laptop-chip charge**
- July 2, 2008: Nvidia cut Q2 revenue guidance to $875–950M (from $1.08–1.11B), citing price cuts, a delayed product and weak demand. It also flagged a one-time $150–200M charge for "a weak die/packaging material set in certain versions of its previous generation GPU and MCP products used in notebook systems." — [EDN](https://www.edn.com/nvidia-cuts-estimate-expects-up-to-200m-charge-on-product-issue/)
- The stock fell 30.7% in one day (July 3, 2008), losing $5.54 to close at $12.49 (pre-split price). Analysts slashed targets. — [Forbes, July 3, 2008](https://www.forbes.com/2008/07/03/nvidia-semiconductors-update-markets-equity-cx_mp_0703markets23.html); [Reuters](https://www.reuters.com/article/markets/stocks/nvidia-shares-tumble-after-q2-warning-idUSN03437345/)
- The final charge was $196 million. Q2 FY2009 net loss was $120.9M on revenue of $892.7M, down 5% year over year. Nvidia simultaneously raised its buyback authorization by $1B, to $2.7B. — [NVIDIA Q2 FY2009 press release (SEC 8-K)](https://www.sec.gov/Archives/edgar/data/1045810/000104581008000018/q209form8kpressrelease.htm)
- The charge was "nearly eight times the $25 million" Nvidia had reserved for warranty costs across all products. Huang called the quarter "disappointing." — [Computerworld](https://www.computerworld.com/article/1567281/bad-graphics-chips-cost-nvidia-196m.html)
- Full FY2009 (ended Jan 25, 2009): revenue $3.42B (vs $4.10B), gross profit $1.17B (vs $1.87B), net loss $30.0M (vs $797.6M profit). R&D still rose 24%, to $855.9M. Q4 alone: revenue $481M, net loss $147.7M. — [NVIDIA Q4 FY2009 press release (SEC)](https://www.sec.gov/Archives/edgar/data/1045810/000104581009000005/pressrelease.htm); [FY2009 10-K](https://www.sec.gov/Archives/edgar/data/1045810/000104581009000013/fy2009form10k.htm)

**Market cap numbers**
- Historical market cap: about $18.9B at end-2007, about $10.4B in June 2008, and about $4.0B in late Nov 2008. End-2008 was about $4.33B, down 77% for the year. It recovered to about $10.4B by end-2009. — [FinHacker NVDA market cap history](https://www.finhacker.cz/en/stocks/nvidia-market-cap/); [StockAnalysis](https://stockanalysis.com/stocks/nvda/market-cap/)
- The lowest 2008 close was on Nov 20, 2008, with the stock "down 76.3% for the year." Daily market cap was about $3.5–3.9B in late Nov/early Dec 2008. — [StatMuse (split-adjusted)](https://www.statmuse.com/money/ask/nvidia-stock-lowest-price-2008-unadjusted); [StatMuse daily](https://www.statmuse.com/money/ask/nvidia-stock-market-cap-2008)
- **⚠ Conflict, Huang's memory vs data:** Huang says Nvidia was worth "six, seven billion or something like that" before CUDA and fell to "like one and a half billion dollars" ([Lex Fridman #494](https://lexfridman.podhood.com/eca4cb06-5e04-43fd-b967-6fa4eea152cf)). Historical data shows about $13B at end-2006 and about $19B at end-2007, with a low of about $3.5B ([FinHacker](https://www.finhacker.cz/en/stocks/nvidia-market-cap/), [StatMuse](https://www.statmuse.com/money/ask/nvidia-stock-market-cap-2008)). Use the data figures, or quote Huang and mark them as his recollection.
- **⚠ Size of the drop:** The New Yorker says "seventy per cent" by end-2008. Market data shows -77% for calendar 2008. One book summary says the stock "fell more than 80%" in 2007–08 ([BFS Invest](https://www.bfsinvest.com/nvidias-jensen-huang-the-ultimate-entrepreneur)); peak-to-trough from late 2007 would be about 80%. All three are roughly consistent depending on start date.

### Inferences
- The narrative beat is that the CUDA bet, a product defect and the global crisis all converged in 2008. Investors couldn't tell a visionary bet from a company in trouble.
- The laptop-chip problem was unrelated to CUDA, but it compounded the margin hit and the loss of credibility.

### Gaps
- I didn't find named analyst quotes from 2007–2009 specifically attacking CUDA spending. The press I found blames price cuts, demand and defects. The "Wall Street hated CUDA" framing comes mainly from later retrospectives (New Yorker, Acquired, Tae Kim).
- I didn't verify which laptop makers were affected (HP, Dell and Apple are commonly cited). Computerworld says only "a range of laptop models from different manufacturers."

---

## 4. Seeding CUDA in universities

### Takeaway
Nvidia co-created one of the first university courses in GPU parallel programming (Illinois, spring 2007). It named UIUC the first "CUDA Center of Excellence" (June 2008) with a $500K gift, donated GPU clusters, co-wrote a textbook (2010), and gave equipment to schools that taught CUDA. The irony is that Nvidia turned down Geoffrey Hinton's 2009 request for a free card.

### Cited Findings
- Nvidia chief scientist David Kirk and Prof. Wen-mei Hwu created and co-taught ECE 498AL, "Programming Massively Parallel Processors," which debuted in spring 2007 and "repeated the following semester due to popular demand." — [Illinois ECE news](https://ece.illinois.edu/news/2522)
- June 30, 2008: UIUC was named "the world's first CUDA Center of Excellence," with NVIDIA donating $500,000. Requirements: schools "must teach a CUDA class and use CUDA technology in their research"; in return NVIDIA supports them "through funding and equipment donations, including help to set up a GPU computing cluster." The previous year NVIDIA had donated 32 QuadroPlex systems (64 GPUs) worth about $800K. — [NVIDIA/UIUC press release](https://www.ks.uiuc.edu/Publications/pdfs/2008-06-30-nvidia.com-NVIDIA_Appoints_First_CUDA_Center_of_Excellence.pdf)
- Kirk: "The CUDA Center of Excellence program rewards schools that truly embrace the concept of parallel processing as the future of computing." — [same press release](https://www.ks.uiuc.edu/Publications/pdfs/2008-06-30-nvidia.com-NVIDIA_Appoints_First_CUDA_Center_of_Excellence.pdf)
- In 2010 Hwu and Kirk co-authored the textbook *Programming Massively Parallel Processors*. — [NVIDIA Research bio of Wen-mei Hwu](https://research.nvidia.com/person/wen-mei-hwu)
- Huang: "went to universities and wrote books and taught classes and put CUDA everywhere… we could put a supercomputer in the hands of every researcher… every student in school, and eventually, something amazing will happen." — [Lex Fridman #494](https://lexfridman.podhood.com/eca4cb06-5e04-43fd-b967-6fa4eea152cf)
- "Nvidia urged universities to adopt its GPUs, offering them computers with CUDA-compatible GPUs in exchange for teaching CUDA programming classes." — [getAbstract review of *The Nvidia Way*](https://journal.getabstract.com/en/review/the-nvidia-saga/)
- Hinton, 2009, after using CUDA for speech recognition: "I sent an e-mail saying, 'Look, I just told a thousand machine-learning researchers they should go and buy Nvidia cards. Can you send me a free one?' … They said no." — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)

### Inferences
- The university push mostly targeted scientific computing (biophysics, physics, engineering), not AI. AI researchers found CUDA through cheap GeForce cards rather than through Nvidia outreach, as the Hinton anecdote shows.

### Gaps
- I didn't find the total number of CUDA Centers of Excellence or CUDA teaching centers by 2010–2017, or the total value of GPUs donated.

---

## 5. AlexNet (2012), Andrew Ng's cat vs. GPUs, and Jensen's pivot to deep learning

### Takeaway
In 2012, Alex Krizhevsky trained AlexNet on two $500-class GeForce GTX 580 gaming cards in his bedroom over five to six days. It won ImageNet with 15.3% top-5 error versus 26.2% for the runner-up, a 10.8-point leap when yearly gains had been about 2 points. Meanwhile, Google's 2012 "cat" network needed 16,000 CPU cores. A Stanford/Nvidia team matched it with 12 GPUs (3 servers) at roughly $20K versus $1M. Huang then sent a Friday email declaring Nvidia was "no longer a graphics company," and by Monday it was an AI company.

### Cited Findings
**AlexNet**
- From the paper: ILSVRC-2012 "winning top-5 test error rate of 15.3%, compared to 26.2% achieved by the second-best entry." The network had 60M parameters and 650,000 neurons. "Our network takes between five and six days to train on two GTX 580 3GB GPUs." The authors added: "All of our experiments suggest that our results can be improved simply by waiting for faster GPUs and bigger datasets." — [Krizhevsky, Sutskever, Hinton, "ImageNet Classification with Deep Convolutional Neural Networks" (NIPS 2012)](http://www.cs.utoronto.ca/~ilya/pubs/2012/imgnet.pdf)
- The network was split across two GPUs because "A single GTX 580 GPU has only 3GB of memory." — [AlexNet paper](http://www.cs.utoronto.ca/~ilya/pubs/2012/imgnet.pdf)
- The GTX 580 was "priced at US$500 upon release." AlexNet was submitted Sept 30, 2012, by team "SuperVision." — [Wikipedia, AlexNet](https://en.wikipedia.org/wiki/AlexNet) (secondary)
- "Whereas the winning error had improved by roughly two percentage points the year before, AlexNet slashed it by more than ten in a single leap." Each GTX 580 delivered about 1.6 TFLOPS, versus about 0.2 TFLOPS for a 2011 quad-core CPU. A CPU "would have required more than a month for every single experiment." Krizhevsky "had to write custom CUDA kernels by hand (cuda-convnet)." — [Dive into Deep Learning textbook, §7.1](https://d2l.smola.org/chapter_convolutional-modern/alexnet.html)
- Hinton: "He had the two G.P.U. boards whirring in his bedroom… Actually, it was his parents who paid for the quite considerable electricity costs." Krizhevsky and Sutskever "bought two GeForce cards from Amazon." — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
- Sutskever: "G.P.U.s showed up and it felt like a miracle." Hinton: "That was a kind of Big Bang moment… That was the paradigm shift." Hinton: "To do machine learning without CUDA would have just been too much trouble." AlexNet "scored so well… that the organizers initially wondered if Krizhevsky had somehow cheated." The New Yorker says he "was the only contestant to use this technique" (neural networks). — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
- Hinton's group had already used CUDA in 2009 to train a speech-recognition neural net. — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
- **⚠ "Bedroom":** This comes from Hinton's quote in the New Yorker, i.e. his parents' house. The paper doesn't mention location.

**Earlier GPU deep learning: Andrew Ng, 2008/2009**
- Ng's three-person Stanford team used two GeForce GTX 280 cards to get "a 70x speedup over CPUs" on a 100M-parameter model, "finishing work that used to require several weeks in a single day." — [NVIDIA Blog, "Why GPUs Are Great for AI"](https://blogs.nvidia.com/blog/why-gpus-are-great-for-ai/). **⚠** NVIDIA dates this "2008". The paper (Raina, Madhavan & Ng) is generally cited as ICML 2009; I didn't verify which date is correct.

**Google's cat vs. GPUs**
- Google's "DistBelief" system "manages to train a neural network using 16000 CPU cores (in 1000 machines)." Stanford's COTS HPC system "trains neural networks at scales comparable to DistBelief with just 3 machines." It scaled to 11B+ parameters "with 2% as many machines." Each server held 4 NVIDIA GTX 680 GPUs, and the code was written in CUDA. Bryan Catanzaro (Nvidia) is a co-author. — [Coates, Huval, Wang, Wu, Catanzaro, Ng, "Deep learning with COTS HPC systems," ICML 2013](https://proceedings.mlr.press/v28/coates13.pdf)
- Cost: "Google's gear cost around $1m, whereas COTS HPC costs around $20,000, according to Wired." — [The Register, June 18, 2013](https://www.theregister.com/software/2013/06/18/google-brain-king-slashes-cost-of-ai-gear/1409139)
- Huang (2016): Google Brain "required 2,000 CPUs… Bryan Catanzaro in NVIDIA Research teamed with Andrew Ng's team at Stanford… 12 NVIDIA GPUs could deliver the deep-learning performance of 2,000 CPUs." — [NVIDIA Blog by Jensen Huang, Jan 12, 2016](https://blogs.nvidia.com/blog/accelerating-ai-artificial-intelligence-gpus/)
- **⚠ CPU count conflict:** The Coates paper says "16,000 CPU cores." The New Yorker says "some sixteen thousand C.P.U.s," and Nvidia says "2,000 CPUs." These likely reconcile as 2,000 multi-core processors equalling 16,000 cores (my inference). Safest phrasing: "16,000 processor cores."
- **Reconciling "12 GPUs" with "3 machines":** 3 servers × 4 GPUs each = 12 GPUs (my arithmetic from the paper's configuration), so both claims describe the same system.
- Wired's "apocryphal" origin story: in 2010, Nvidia's Bill Dally had breakfast with Ng, who was "trying to find cats on the internet." Dally: "I bet we could do it with just a few GPUs." Catanzaro did it "with just 12 GPUs." But Catanzaro, who joined Nvidia in 2008 after GPU-for-AI work at Berkeley, insists "NVIDIA's position in this market is not an accident." — [WIRED](https://www.wired.com/story/nvidia-ai-chips/)

**Jensen's pivot**
- "In 2013, on the basis of promising research from the academic computer-science community, Huang bet Nvidia's future on artificial intelligence." Catanzaro had doubts: "I didn't want him to fall into the same trap that the A.I. industry has had in the past… But, ten years plus down the road, he was right." — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
- Greg Estes (Nvidia VP): "He sent out an e-mail on Friday evening saying everything is going to deep learning, and that we were no longer a graphics company… By Monday morning, we were an A.I. company. Literally, it was that fast." — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
- Huang told Catanzaro "to imagine he'd marched all eight thousand of Nvidia's employees into the parking lot… I was free to select anyone from the parking lot to join my team." — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
- Huang: "The fact that they can solve computer vision, which is completely unstructured, leads to the question 'What else can you teach it?'" — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
- Huang (2016) credited "Yann LeCun's work in convolutional neural nets, Geoff Hinton's back-propagation… and Andrew Ng's large-scale use of GPUs" with igniting "the big bang of modern AI." He also said Nvidia "sped up training deep neural networks by 50x in just three years." — [NVIDIA Blog, Jan 2016](https://blogs.nvidia.com/blog/accelerating-ai-artificial-intelligence-gpus/)
- "Within a couple of years, every entrant in the ImageNet competition was using a neural network. By the mid-twenty-tens, neural networks trained on G.P.U.s were identifying images with ninety-six-per-cent accuracy, surpassing humans." — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)

### Inferences
- The dramatic contrast for viewers is that Google used a warehouse of about 1,000 computers while a grad student used two gaming cards bought on Amazon. Note that Google's cat network and AlexNet solved different tasks, so the comparison is about scale of hardware, not a head-to-head.

### Gaps
- I couldn't find the exact date of Huang's "Friday email." The New Yorker places the pivot in 2013 but gives no date.
- I didn't find a direct Huang quote describing his reaction to AlexNet in 2012 itself.

---

## 6. cuDNN (2014), DGX-1 (2016), and the first DGX-1 delivered to OpenAI

### Takeaway
cuDNN, launched Sept 7, 2014, packaged the hand-tuned math that Krizhevsky had to write himself into a free library, so AI frameworks could use GPUs without CUDA expertise. The DGX-1, announced April 2016 at $129,000 and billed as "250 servers in a box", was Nvidia's first purpose-built AI supercomputer. In August 2016, Huang personally delivered the first unit to OpenAI with a handwritten dedication.

### Cited Findings
**cuDNN**
- Sept 7, 2014: NVIDIA introduced cuDNN, "a GPU-accelerated library of primitives for deep neural networks" (convolution, pooling, softmax, ReLU/Sigmoid/Tanh). It was "designed to be integrated into higher-level machine learning frameworks, such as UC Berkeley's popular Caffe," letting developers "focus on designing and implementing neural net models rather than tuning for performance." — [NVIDIA Developer Forums announcement](https://forums.developer.nvidia.com/t/announcing-nvidia-reg-cudnn-ndash-gpu-accelerated-machine-learning/34741)
- NVIDIA claimed "more than a 10X speed-up when training the 'reference Imagenet' DNN model on an NVIDIA Tesla K40 GPU, compared to an Intel IvyBridge CPU." — [NVIDIA Technical Blog, Sept 7, 2014](https://developer.nvidia.com/blog/accelerate-machine-learning-cudnn-deep-neural-network-library/)
- **⚠ Counter-claim:** A forum commenter at the time said an optimized CPU version of Caffe was "< 2x (not 11x!) slower" than the GPU. Speedup claims depended heavily on CPU optimization. — [NVIDIA Developer Forums thread](https://forums.developer.nvidia.com/t/accelerate-machine-learning-with-the-cudnn-deep-neural-network-library/148429/10)

**DGX-1 and OpenAI**
- The DGX-1 was announced April 2016, "described as equivalent in power to '250 servers in a box' and costing $129,000." — [Fortune, Aug 15, 2016](https://fortune.com/2016/08/15/elon-musk-artificial-intelligence-openai-nvidia-supercomputer/)
- Specs: 8 Tesla P100 GPUs plus 2 Intel Xeon CPUs. — [Arne AI museum entry](https://arne.ai/museum/items/nvidia-dgx-1). NVLink interconnect, 7.68TB SSD, and 12x faster than the previous four-way Maxwell solution. — [IT之家 (ITHome)](https://www.ithome.com/0/751/080.htm)
- "Computations that would take 250 hours on a conventional computer take about 10 hours on the DGX-1." OpenAI planned to feed it Reddit threads to build language models. — [MIT Technology Review, Aug 15, 2016](https://www.technologyreview.com/2016/08/15/158311/this-supercomputer-will-try-to-find-intelligence-on-reddit)
- Huang "personally delivered the supercomputer… last week to OpenAI's San Francisco office." His handwritten note on the case read: **"To Elon & the OpenAI Team! To the future of computing and humanity. I present you the World's First DGX-1!"** — [Fortune, 2016](https://fortune.com/2016/08/15/elon-musk-artificial-intelligence-openai-nvidia-supercomputer/); [Fortune, 2024](https://fortune.com/2024/02/22/jensen-huang-elon-musk-openai-first-ai-supercomputer-sam-altman/); [ITHome (photos shared by Musk in 2024)](https://www.ithome.com/0/751/080.htm)
- Musk tweeted on Aug 9, 2016: "Would like to thank @nvidia and Jensen for donating the first DGX-1 AI supercomputer to @OpenAI in support of democratizing AI technology." — [Fortune, 2016](https://fortune.com/2016/08/15/elon-musk-artificial-intelligence-openai-nvidia-supercomputer/)
- "Elon Musk, then the chairman, opened the package with a box cutter." — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
- Huang at the time: "I thought it was incredibly appropriate that the world's first supercomputer dedicated to artificial intelligence would go to the laboratory that was dedicated to open artificial intelligence." Later (NYT DealBook, 2023): "It took us five years to make it." He described it as a 70-pound, 35,000-part computer. — [Fortune, Feb 22, 2024](https://fortune.com/2024/02/22/jensen-huang-elon-musk-openai-first-ai-supercomputer-sam-altman/)
- Context: Marc Andreessen (2016): "every single one [of our deep-learning startups] effectively comes in building on Nvidia's platform." Google's transformer followed in 2017, and OpenAI's GPT models were trained on Nvidia supercomputers. — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)

### Inferences
- There is a neat bookend: in 2009 Nvidia refused Hinton a free card. Seven years later its CEO hand-delivered a $129K AI supercomputer as a gift to an AI lab. Hinton's former student Ilya Sutskever (AlexNet co-author) was OpenAI's chief scientist at the time. That last point comes from general knowledge and wasn't re-verified in these sources.

### Gaps
- I didn't verify the exact delivery date. Musk's tweet is Aug 9, 2016, and Fortune says "last week" on Aug 15.

---

## 7. How the CUDA ecosystem became a moat competitors couldn't copy

### Takeaway
The moat was never the CUDA language itself. It was a decade-plus head start in install base, tuned libraries (cuBLAS, cuFFT, cuDNN), teaching, and the fact that the entire AI research field was already written in CUDA when deep learning exploded. The open alternative, OpenCL (2008–09, Apple → Khronos), fragmented under committee politics and lacked AI libraries. AMD's ROCm/HIP (~2016) arrived late with narrower support.

### Cited Findings
- Huang: "Install base defines an architecture… there were other architectures at the time. CUDA came out, OpenCL was here… the decision that we made that was good was we said… ultimately, it's about install base." — [Lex Fridman #494](https://lexfridman.podhood.com/eca4cb06-5e04-43fd-b967-6fa4eea152cf). The podcast summary says Huang called CUDA's install base Nvidia's biggest moat: "If I were a developer today, I would target CUDA first." — [same](https://lexfridman.podhood.com/eca4cb06-5e04-43fd-b967-6fa4eea152cf)
- Libraries were part of CUDA from v1.0 (CUBLAS, CUFFT in 2007) — [CUDA Programming Guide 1.0](https://developer.download.nvidia.com/compute/cuda/1.0/NVIDIA_CUDA_Programming_Guide_1.0.pdf). The 2014 CUDA 6.5 toolkit bundled cuFFT, cuBLAS, cuSPARSE, cuRAND, NPP, Thrust and cuDNN as a "free download" — [CUDA 6.5 Performance Report](https://developer.download.nvidia.com/compute/cuda/6_5/rel/docs/CUDA_6.5_Performance_Report.pdf)
- "NVIDIA spent the following fifteen years doing the unglamorous work: building tuned libraries, funding university courses, seeding research labs with hardware… When cuDNN arrived and the deep-learning explosion hit… the entire field was already written in CUDA, because that's what the researchers had been handed." OpenCL, launched 2009, failed through "fragmented implementations, weaker tooling, and… no vendor with a reason to push it hard for machine learning." The guide adds: "a standard without an ecosystem is just a document." — [Big Iron guide (2026)](https://www.bigiron.cc/guides/cuda-vs-rocm-vs-vulkan-vs-sycl-the-compute-api-landscape)
- Insider account of OpenCL's failure from Modular's "Democratizing AI Compute" series, written by someone who was at Apple during OpenCL's creation. Committee development was "glacial"; vendors kept innovations secret and used "vendor-specific extensions"; Apple contributed a spec "but without a full reference implementation," producing "a patchwork of vendor-specific forks." Meanwhile "NVIDIA maintained a token OpenCL implementation—but it was strategically hobbled (e.g., not being able to use TensorCores)." — [Modular blog, Democratizing AI Compute Part 5](https://www.modular.com/blog/democratizing-ai-compute-part-5-what-about-cuda-c-alternatives)
- "OpenCL was born in 2008-2009 on Apple's initiative… It guaranteed code portability but not performance portability… Apple itself deprecated it in 2018." AMD launched ROCm "around 2016, with HIP as a language deliberately almost identical to CUDA." Its problems were "limited support for consumer cards, breaking changes between versions, less polished documentation, incomplete coverage of equivalent libraries." — [Michele Laurelli, "CUDA, Nvidia's Real Moat"](https://blog.michelelaurelli.it/en/cuda-il-vero-fossato-di-nvidia/)
- ROCm's ecosystem is "relatively young compared to CUDA" with "more limited documentation and community resources." — [HPCwire, June 2024](https://www.hpcwire.com/2024/06/21/spelunking-the-hpc-and-ai-gpu-software-stacks/)
- Scale today (outside the 2003–2017 window, useful for an epilogue): "more than 5 million CUDA developers… 300 software libraries… about 500 million CUDA-capable Nvidia GPUs in the market." — [BFS Invest summary of *The Nvidia Way*](https://www.bfsinvest.com/nvidias-jensen-huang-the-ultimate-entrepreneur); [Chip Insights](https://chipinsights.net/p/how-to-build-a-new-chip-architecture). **⚠** These are secondary sources and Nvidia marketing-derived numbers.

### Inferences
- The moat is a flywheel: cheap GeForce cards everywhere, so researchers use CUDA, so libraries and papers are CUDA-first, so everyone buys Nvidia, so the next tool is CUDA-first. Competitors could copy the syntax (HIP is nearly identical), but they couldn't copy ten years of tuned libraries and habits.
- Note for accuracy: most moat analyses are 2024–2026 hindsight. During 2007–2012 the outcome was not obvious, since CUDA downloads were falling from 2009 to 2012 per the New Yorker.

### Gaps
- I found no reliable year-by-year figures for CUDA downloads or developer counts in 2007–2017. The New Yorker gives only the shape: peak in 2009, then three years of decline.
- I didn't find contemporaneous (2009–2012) AMD statements on OpenCL strategy.

---

## Appendix (within scope): Memorable quotes and everyday analogies

> Kept under this heading for the report writer. All are sourced above.

### Short quotes (pick 3–6)
1. **"We were democratizing supercomputing."** — Jensen Huang, [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
2. **"I just told a thousand machine-learning researchers they should go and buy Nvidia cards. Can you send me a free one?… They said no."** — Geoffrey Hinton, [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
3. **"G.P.U.s showed up and it felt like a miracle."** — Ilya Sutskever, [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
4. **"He had the two G.P.U. boards whirring in his bedroom… it was his parents who paid for the quite considerable electricity costs."** — Hinton, [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
5. **"By Monday morning, we were an A.I. company. Literally, it was that fast."** — Greg Estes, Nvidia VP, [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
6. **"We increased our cost by fifty percent… and we were a thirty-five percent gross margin company."** — Huang, [Lex Fridman #494](https://lexfridman.podhood.com/eca4cb06-5e04-43fd-b967-6fa4eea152cf)
7. **"To Elon & the OpenAI Team! To the future of computing and humanity. I present you the World's First DGX-1!"** — Huang's handwritten note, [Fortune](https://fortune.com/2016/08/15/elon-musk-artificial-intelligence-openai-nvidia-supercomputer/)
8. **"It required a PhD in computer graphics to be able to port an application to the GPU."** — Ian Buck, [Tom's Hardware](https://www.tomshardware.com/reviews/ian-buck-nvidia,2393.html)
9. **"That was a kind of Big Bang moment… That was the paradigm shift."** — Hinton on AlexNet, [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)

### Everyday analogies used by others
1. **Delivery truck vs. motorcycle fleet:** "A C.P.U. functions like a delivery truck, dropping off one package at a time; a G.P.U. is more like a fleet of motorcycles spreading across a city." — Stephen Witt, [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
2. **One paintball gun vs. 1,100 barrels (Mythbusters, NVISION 2008):** Adam Savage and Jamie Hyneman, hired by Nvidia, showed a single-barrel "CPU" robot slowly painting a smiley face pixel by pixel. A massive multi-barrel "GPU" gun then fired all at once, painting the Mona Lisa in about 275 milliseconds. — [Gizmodo](https://gizmodo.com/mythbusters-build-a-1100-barrel-paintball-gun-to-paint-5043303); [WIRED](https://www.wired.com/2008/08/video-2100-barr/). **⚠ Barrel count conflict:** Gizmodo, TechCrunch and Laughing Squid say 1,100 barrels; WIRED says 2,100. Even TechCrunch's URL says "2100" while its headline says "1100." Check the original video before stating a number. TechCrunch also called the demo "awfully misleading" since CPUs were going multi-core ([TechCrunch](https://techcrunch.com/2008/08/28/mythbusters-gpu-vs-cpu-demo-2100-paintballs-make-the-mona-lisa-in-275ms/)).
3. **Directions to Starbucks (why parallel thinking is hard):** Buck: "You give instructions to someone on how to get from here to Starbucks, and you give them individual steps. You don't give them instructions on how to get to any Starbucks location from anywhere. It's just hard to think that way, in parallel." — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)
4. **Flipping a switch (what CUDA did):** CUDA was "like you flipped the switch on the graphics card and it turned from being a video game component into a low-budget supercomputer." — Stephen Witt, [Front Row Podcast](https://www.ykeith.com/p/witt)
5. **Field of Dreams (the strategy):** Witt compared Huang to Kevin Costner's character, who builds a baseball field in a cornfield: "There were no customers at the time that he was building this. He built it in anticipation that someday, if he built it, they would come." — [NPR, March 18, 2024](https://www.npr.org/2024/03/18/1239283003/how-nvidia-dominated-the-ai-chip-market)
6. **A million tiny programs, 60 times a second (why GPUs were already parallel):** Buck on game shaders: tiny programs "running on every pixel on the screen; a million pixels, sixty times per second." — [NVIDIA Technical Blog](https://developer.nvidia.com/blog/inside-the-programming-evolution-of-gpu-computing/)
7. **Chip as a city plan:** Nvidia chip lead Arjun Prabhu compared chip design to "urban planning, with different zones of the chip dedicated to different tasks." — [The New Yorker](https://www.newyorker.com/magazine/2023/12/04/how-jensen-huangs-nvidia-is-powering-the-ai-revolution)

*(Unsourced suggestion for the scriptwriter, my own and not from a source: "A CPU is a brilliant math professor; a GPU is a stadium of 10,000 schoolkids who each know only arithmetic. To grade one hard proof, hire the professor. To add up a million pairs of numbers, hire the stadium.")*
