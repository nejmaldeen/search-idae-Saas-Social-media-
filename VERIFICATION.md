# تقرير التحقق من التكامل — Integration Verification

- **وقت التشغيل:** 2026-11-16T07:20:52Z
- **الغرض:** إثبات أن كل منصة تُسلّم ما سيحتاجه البحث الحقيقي — لا بحث سوقي.

## الملخص

| المنصة | جاهزة | النتيجة | عناصر العيّنة | زمن | ملاحظة |
|---|---|---|---|---|---|
| youtube | ✅ | 10/12 | 36 | 20.9s | status=ok reason=transcripts=2/2 (skipped 0 without a usable |
| tiktok | ✅ | 10/12 | 21 | 60.1s | status=ok reason=search_actor=clockworks~tiktok-scraper rows |
| x | ✅ | 10/11 | 4 | 7.8s | status=partial reason=search_actor=kaitoeasyapi~twitter-x-da |
| instagram | ✅ | 10/12 | 6 | 45.9s | status=ok reason=search_actor=apify~instagram-scraper rows=4 |
| snapchat | ✅ | 9/10 | 36 | 3.7s | status=ok reason=search_actor=parseforge~snapchat-scraper ro |

## التفاصيل

### youtube

- **التكلفة المقاسة:** $0.002
- status=ok reason=transcripts=2/2 (skipped 0 without a usable track)

| # | المعيار | الحالة | الدليل |
|---|---|---|---|
| C01 | البحث بالعربية يُرجع نتائج | ✅ PASS | query 'مشاكل المتاجر الإلكترونية' -> 36 items, 36 containing Arabic |
| C02 | جلب تعليقات المستخدمين لا الأوصاف فقط | ✅ PASS | 30 comment item(s) retrieved |
| C03 | كل عنصر له رابط مصدر | ✅ PASS | 36/36 items carry a source URL (100%) |
| C04 | اسم المؤلف وتاريخ النشر محفوظان | ✅ PASS | author on 34/36, publish date on 34/36 |
| C05 | مقاييس التفاعل (مشاهدات/إعجابات/تعليقات/مشاركات) | ✅ PASS | 34/36 items carry metrics; fields seen: comments_count, likes, views |
| C06 | الردود على التعليقات متاحة | ⚠️ PARTIAL | commentThreads reports totalReplyCount (16 sampled item(s) have replies) but fetching the reply bodies needs a second comments.list call, which is not implemented |
| C07 | العمق والسقف لكل استعلام | ✅ PASS | requested 4, received 36 in 20.9s. Documented ceiling: 10,000 quota units/day. search.list costs 100 units; commentThreads.list costs 1. |
| C08 | التصفية الزمنية | ⚠️ PARTIAL | 4 inside / 61 outside / 1 undated after a 180d window - filtering is not fully enforced upstream |
| C09 | سلوك واضح عند الفشل | ✅ PASS | empty/failed result reported explicitly as 'ok' with reason 'None' - no silent success |
| C10 | التكلفة مقاسة فعلياً | ✅ PASS | measured $0.002 for 36 item(s) = $0.056 per 1,000 |
| C11 | الوصول للجمهور السعودي/العربي | ✅ PASS | 36/36 sampled items are Arabic (100%) |
| C12 | تفريغ نصي لما يقوله الفيديو | ✅ PASS | 2 transcript(s); longest 5900 chars; 2 contain Arabic; 2 are the speaker's own language (not machine-translated) |

### tiktok

- **التكلفة المقاسة:** $0.092
- status=ok reason=search_actor=clockworks~tiktok-scraper rows=4 mapped=4 | comments_actor=clockworks~tiktok-comments-scraper rows=17 mapped=17 | skipped=0

| # | المعيار | الحالة | الدليل |
|---|---|---|---|
| C01 | البحث بالعربية يُرجع نتائج | ✅ PASS | query 'مشاكل متجر سلة' -> 21 items, 19 containing Arabic |
| C02 | جلب تعليقات المستخدمين لا الأوصاف فقط | ✅ PASS | 17 comment item(s) retrieved |
| C03 | كل عنصر له رابط مصدر | ✅ PASS | 21/21 items carry a source URL (100%) |
| C04 | اسم المؤلف وتاريخ النشر محفوظان | ✅ PASS | author on 21/21, publish date on 21/21 |
| C05 | مقاييس التفاعل (مشاهدات/إعجابات/تعليقات/مشاركات) | ✅ PASS | 21/21 items carry metrics; fields seen: comments_count, likes, saves, shares, views |
| C06 | الردود على التعليقات متاحة | ✅ PASS | replies enabled (replies_per_comment=3): the run returned 3 comment item(s). search_actor=clockworks~tiktok-scraper rows=2 mapped=2 / comments_actor=clockworks~tiktok-comments-scraper row |
| C07 | العمق والسقف لكل استعلام | ✅ PASS | requested 4, received 21 in 60.1s. Documented ceiling: Billed per result by the provider (~$1.70-3.70 / 1,000 as of Nov 2026). |
| C08 | التصفية الزمنية | ✅ PASS | window of 180d honoured: 8 item(s) inside, 0 outside, 0 undated |
| C09 | سلوك واضح عند الفشل | ⚠️ PARTIAL | a nonsense query still returned items - results may be fuzzy |
| C10 | التكلفة مقاسة فعلياً | ✅ PASS | measured $0.092 for 21 item(s) = $4.381 per 1,000 |
| C11 | الوصول للجمهور السعودي/العربي | ✅ PASS | 19/21 sampled items are Arabic (90%) |
| C12 | تفريغ نصي لما يقوله الفيديو | ⚠️ PARTIAL | subtitle tracks are published (ara-SA, eng-US; Arabic available) but the subtitle CDN host is not reachable from this environment, so the text cannot be downloaded yet |

### x

- **التكلفة المقاسة:** $0.0025
- status=partial reason=search_actor=kaitoeasyapi~twitter-x-data-tweet-scraper-pay-per-result-cheapest rows=15 mapped=4 | marker_rows=11 (placeholder id=-1) | skipped=0

| # | المعيار | الحالة | الدليل |
|---|---|---|---|
| C01 | البحث بالعربية يُرجع نتائج | ✅ PASS | query 'متجر الكتروني مشكلة' -> 4 items, 3 containing Arabic |
| C02 | جلب تعليقات المستخدمين لا الأوصاف فقط | ✅ PASS | 4 post(s) retrieved; on x a post is itself a user voice, not publisher content |
| C03 | كل عنصر له رابط مصدر | ✅ PASS | 4/4 items carry a source URL (100%) |
| C04 | اسم المؤلف وتاريخ النشر محفوظان | ✅ PASS | author on 4/4, publish date on 4/4 |
| C05 | مقاييس التفاعل (مشاهدات/إعجابات/تعليقات/مشاركات) | ✅ PASS | 4/4 items carry metrics; fields seen: comments_count, likes, saves, shares, views |
| C06 | الردود على التعليقات متاحة | ⚠️ PARTIAL | the actor accepts conversationIds, so a thread can be pulled, but threading is not wired into the connector |
| C07 | العمق والسقف لكل استعلام | ✅ PASS | requested 4, received 4 in 7.8s. Documented ceiling: Provider per-result billing. Official X alternative: pay-per-use, ~$0.005 per post read, no free tier (Nov 2026). |
| C08 | التصفية الزمنية | ✅ PASS | window of 180d honoured: 4 item(s) inside, 0 outside, 0 undated |
| C09 | سلوك واضح عند الفشل | ✅ PASS | empty/failed result reported explicitly as 'error' with reason 'actor=kaitoeasyapi~twitter-x-data-tweet-scraper-pay-per-result-cheapest returned 15 marker' - no silent success |
| C10 | التكلفة مقاسة فعلياً | ✅ PASS | measured $0.0025 for 4 item(s) = $0.625 per 1,000 |
| C11 | الوصول للجمهور السعودي/العربي | ✅ PASS | 3/4 sampled items are Arabic (75%) |
| C12 | تفريغ نصي لما يقوله الفيديو | ➖ NA | text-only platform: there is nothing spoken to transcribe |

### instagram

- **التكلفة المقاسة:** $0.1187
- status=ok reason=search_actor=apify~instagram-scraper rows=4 mapped=4 | comments_actor=apify~instagram-comment-scraper rows=3 mapped=0 | transcripts=2 | skipped=3

| # | المعيار | الحالة | الدليل |
|---|---|---|---|
| C01 | البحث بالعربية يُرجع نتائج | ✅ PASS | query 'متجر_الكتروني' -> 6 items, 6 containing Arabic |
| C02 | جلب تعليقات المستخدمين لا الأوصاف فقط | ❌ FAIL | items returned but none are comments - only captions/metadata |
| C03 | كل عنصر له رابط مصدر | ✅ PASS | 6/6 items carry a source URL (100%) |
| C04 | اسم المؤلف وتاريخ النشر محفوظان | ✅ PASS | author on 6/6, publish date on 6/6 |
| C05 | مقاييس التفاعل (مشاهدات/إعجابات/تعليقات/مشاركات) | ✅ PASS | 4/6 items carry metrics; fields seen: comments_count, likes |
| C06 | الردود على التعليقات متاحة | ❌ FAIL | enabling replies produced no comments: ok search_actor=apify~instagram-scraper rows=2 mapped=2 / comments_actor=apify~instagram-comment-scraper rows=1 mapped=0 /  |
| C07 | العمق والسقف لكل استعلام | ✅ PASS | requested 4, received 6 in 45.9s. Documented ceiling: ~$1.50-2.70 / 1,000 results as of Nov 2026. |
| C08 | التصفية الزمنية | ✅ PASS | window of 180d honoured: 6 item(s) inside, 0 outside, 0 undated |
| C09 | سلوك واضح عند الفشل | ✅ PASS | empty/failed result reported explicitly as 'error' with reason 'actor=apify~instagram-scraper returned 1 marker row(s) and no content: error=no_items. The' - no silent success |
| C10 | التكلفة مقاسة فعلياً | ✅ PASS | measured $0.1187 for 6 item(s) = $19.783 per 1,000 |
| C11 | الوصول للجمهور السعودي/العربي | ✅ PASS | 6/6 sampled items are Arabic (100%) |
| C12 | تفريغ نصي لما يقوله الفيديو | ✅ PASS | 2 transcript(s); longest 206 chars; 2 contain Arabic; 2 are the speaker's own language (not machine-translated) |

### snapchat

- **التكلفة المقاسة:** $0.0078
- status=ok reason=search_actor=parseforge~snapchat-scraper rows=4 mapped=4 | embedded_comments=32 | skipped=0

| # | المعيار | الحالة | الدليل |
|---|---|---|---|
| C01 | البحث بالعربية يُرجع نتائج | ➖ NA | profile-driven platform: no keyword search exists |
| C02 | جلب تعليقات المستخدمين لا الأوصاف فقط | ✅ PASS | 32 comment item(s) retrieved |
| C03 | كل عنصر له رابط مصدر | ✅ PASS | 36/36 items carry a source URL (100%) |
| C04 | اسم المؤلف وتاريخ النشر محفوظان | ✅ PASS | author on 32/36, publish date on 36/36 |
| C05 | مقاييس التفاعل (مشاهدات/إعجابات/تعليقات/مشاركات) | ✅ PASS | 36/36 items carry metrics; fields seen: author_followers, comments_count, likes, saves, shares, views |
| C06 | الردود على التعليقات متاحة | ➖ NA | comments are returned inline; Snapchat exposes no reply threading |
| C07 | العمق والسقف لكل استعلام | ✅ PASS | requested 4, received 36 in 3.7s. Documented ceiling: NO KEYWORD SEARCH on any available actor: collection is driven by a list of usernames the operator supplies, so Snapchat is a MONITORING |
| C08 | التصفية الزمنية | ✅ PASS | window of 180d honoured: 36 item(s) inside, 0 outside, 0 undated |
| C09 | سلوك واضح عند الفشل | ✅ PASS | empty/failed result reported explicitly as 'error' with reason 'actor=parseforge~snapchat-scraper returned 1 marker row(s) and no content: error=@zzzqqqxx' - no silent success |
| C10 | التكلفة مقاسة فعلياً | ✅ PASS | measured $0.0078 for 36 item(s) = $0.217 per 1,000 |
| C11 | الوصول للجمهور السعودي/العربي | ❌ FAIL | 0/36 sampled items are Arabic (0%) |
| C12 | تفريغ نصي لما يقوله الفيديو | ✅ PASS | 4 transcript(s); longest 13 chars; 0 contain Arabic; 4 are the speaker's own language (not machine-translated) |

## مفتاح الحالات

- ✅ **PASS** — مُثبت بدليل من تشغيل حقيقي
- ⚠️ **PARTIAL** — يعمل جزئياً أو القدرة موجودة ولم تُفعّل في هذا الفحص
- ❌ **FAIL** — لا يعمل، والسبب مذكور
- ➖ **NA** — لا ينطبق على هذه المنصة
- ❓ **UNTESTED** — لم يُشغَّل؛ **لا يُحسب نجاحاً**

## التكلفة المقاسة فعلياً (C10)

- أُنفق خلال هذا التحقق: **$0.223**
- عناصر مجلوبة: **103**
- **التكلفة لكل ١٠٠٠ عنصر: $2.165**
