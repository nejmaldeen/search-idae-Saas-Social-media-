# تقرير التحقق من التكامل — Integration Verification

- **وقت التشغيل:** 2026-11-15T11:41:02Z
- **الغرض:** إثبات أن كل منصة تُسلّم ما سيحتاجه البحث الحقيقي — لا بحث سوقي.

## الملخص

| المنصة | جاهزة | النتيجة | عناصر العيّنة | زمن | ملاحظة |
|---|---|---|---|---|---|
| snapchat | ✅ | 7/9 | 51 | 2.5s | status=ok reason=search_actor=parseforge~snapchat-scraper ro |
| tiktok | ✅ | 10/11 | 26 | 59.2s | status=ok reason=search_actor=clockworks~tiktok-scraper rows |
| youtube | ✅ | 10/11 | 84 | 3.2s | status=ok reason=None |
| instagram | ✅ | 9/11 | 5 | 19.4s | status=ok reason=search_actor=apify~instagram-scraper rows=5 |
| x | ✅ | 2/11 | 0 | 2.4s | status=error reason=actor=apidojo~tweet-scraper returned 10  |

## التفاصيل

### snapchat

- **التكلفة المقاسة:** $0.0107
- status=ok reason=search_actor=parseforge~snapchat-scraper rows=5 mapped=5 | embedded_comments=46 | skipped=0

| # | المعيار | الحالة | الدليل |
|---|---|---|---|
| C01 | البحث بالعربية يُرجع نتائج | ➖ NA | profile-driven platform: no keyword search exists |
| C02 | جلب تعليقات المستخدمين لا الأوصاف فقط | ✅ PASS | 46 comment item(s) retrieved |
| C03 | كل عنصر له رابط مصدر | ✅ PASS | 51/51 items carry a source URL (100%) |
| C04 | اسم المؤلف وتاريخ النشر محفوظان | ✅ PASS | author on 46/51, publish date on 51/51 |
| C05 | مقاييس التفاعل (مشاهدات/إعجابات/تعليقات/مشاركات) | ✅ PASS | 51/51 items carry metrics; fields seen: author_followers, comments_count, likes, saves, shares, views |
| C06 | الردود على التعليقات متاحة | ➖ NA | comments are returned inline; Snapchat exposes no reply threading |
| C07 | العمق والسقف لكل استعلام | ✅ PASS | requested 5, received 51 in 2.5s. Documented ceiling: NO KEYWORD SEARCH on any available actor: collection is driven by a list of usernames the operator supplies, so Snapchat is a MONITORING |
| C08 | التصفية الزمنية | ⚠️ PARTIAL | no date filter exposed; filter client-side on uploadedAt |
| C09 | سلوك واضح عند الفشل | ✅ PASS | empty/failed result reported explicitly as 'error' with reason 'actor=parseforge~snapchat-scraper returned 1 marker row(s) and no content: error=@zzzqqqxx' - no silent success |
| C10 | التكلفة مقاسة فعلياً | ✅ PASS | measured $0.0107 for 51 item(s) = $0.21 per 1,000 |
| C11 | الوصول للجمهور السعودي/العربي | ❌ FAIL | 0/51 sampled items are Arabic (0%) |

### tiktok

- **التكلفة المقاسة:** $0.0714
- status=ok reason=search_actor=clockworks~tiktok-scraper rows=5 mapped=5 | comments_actor=clockworks~tiktok-comments-scraper rows=21 mapped=21 | skipped=0

| # | المعيار | الحالة | الدليل |
|---|---|---|---|
| C01 | البحث بالعربية يُرجع نتائج | ✅ PASS | query 'مشاكل متجر سلة' -> 26 items, 26 containing Arabic |
| C02 | جلب تعليقات المستخدمين لا الأوصاف فقط | ✅ PASS | 21 comment item(s) retrieved |
| C03 | كل عنصر له رابط مصدر | ✅ PASS | 26/26 items carry a source URL (100%) |
| C04 | اسم المؤلف وتاريخ النشر محفوظان | ✅ PASS | author on 26/26, publish date on 26/26 |
| C05 | مقاييس التفاعل (مشاهدات/إعجابات/تعليقات/مشاركات) | ✅ PASS | 26/26 items carry metrics; fields seen: comments_count, likes, saves, shares, views |
| C06 | الردود على التعليقات متاحة | ✅ PASS | replies enabled (replies_per_comment=3): the run returned 3 comment item(s). search_actor=clockworks~tiktok-scraper rows=2 mapped=2 / comments_actor=clockworks~tiktok-comments-scraper row |
| C07 | العمق والسقف لكل استعلام | ✅ PASS | requested 5, received 26 in 59.2s. Documented ceiling: Billed per result by the provider (~$1.70-3.70 / 1,000 as of Nov 2026). |
| C08 | التصفية الزمنية | ✅ PASS | oldestPostDateUnified / newestPostDate on the search actor |
| C09 | سلوك واضح عند الفشل | ⚠️ PARTIAL | a nonsense query still returned items - results may be fuzzy |
| C10 | التكلفة مقاسة فعلياً | ✅ PASS | measured $0.0714 for 26 item(s) = $2.746 per 1,000 |
| C11 | الوصول للجمهور السعودي/العربي | ✅ PASS | 26/26 sampled items are Arabic (100%) |

### youtube

- **التكلفة المقاسة:** $0.0037
- status=ok reason=None

| # | المعيار | الحالة | الدليل |
|---|---|---|---|
| C01 | البحث بالعربية يُرجع نتائج | ✅ PASS | query 'مشاكل المتاجر الإلكترونية' -> 84 items, 84 containing Arabic |
| C02 | جلب تعليقات المستخدمين لا الأوصاف فقط | ✅ PASS | 79 comment item(s) retrieved |
| C03 | كل عنصر له رابط مصدر | ✅ PASS | 84/84 items carry a source URL (100%) |
| C04 | اسم المؤلف وتاريخ النشر محفوظان | ✅ PASS | author on 84/84, publish date on 84/84 |
| C05 | مقاييس التفاعل (مشاهدات/إعجابات/تعليقات/مشاركات) | ✅ PASS | 84/84 items carry metrics; fields seen: comments_count, likes, views |
| C06 | الردود على التعليقات متاحة | ⚠️ PARTIAL | commentThreads reports totalReplyCount (22 sampled item(s) have replies) but fetching the reply bodies needs a second comments.list call, which is not implemented |
| C07 | العمق والسقف لكل استعلام | ✅ PASS | requested 5, received 84 in 3.2s. Documented ceiling: 10,000 quota units/day. search.list costs 100 units; commentThreads.list costs 1. |
| C08 | التصفية الزمنية | ✅ PASS | publishedAfter / publishedBefore on search.list |
| C09 | سلوك واضح عند الفشل | ✅ PASS | empty/failed result reported explicitly as 'ok' with reason 'None' - no silent success |
| C10 | التكلفة مقاسة فعلياً | ✅ PASS | measured $0.0037 for 84 item(s) = $0.044 per 1,000 |
| C11 | الوصول للجمهور السعودي/العربي | ✅ PASS | 84/84 sampled items are Arabic (100%) |

### instagram

- **التكلفة المقاسة:** $0.0267
- status=ok reason=search_actor=apify~instagram-scraper rows=5 mapped=5 | comments_actor=apify~instagram-comment-scraper rows=3 mapped=0 | skipped=3

| # | المعيار | الحالة | الدليل |
|---|---|---|---|
| C01 | البحث بالعربية يُرجع نتائج | ✅ PASS | query 'متجر_الكتروني' -> 5 items, 5 containing Arabic |
| C02 | جلب تعليقات المستخدمين لا الأوصاف فقط | ❌ FAIL | items returned but none are comments - only captions/metadata |
| C03 | كل عنصر له رابط مصدر | ✅ PASS | 5/5 items carry a source URL (100%) |
| C04 | اسم المؤلف وتاريخ النشر محفوظان | ✅ PASS | author on 5/5, publish date on 5/5 |
| C05 | مقاييس التفاعل (مشاهدات/إعجابات/تعليقات/مشاركات) | ✅ PASS | 5/5 items carry metrics; fields seen: comments_count, likes |
| C06 | الردود على التعليقات متاحة | ❌ FAIL | enabling replies produced no comments: ok search_actor=apify~instagram-scraper rows=2 mapped=2 / comments_actor=apify~instagram-comment-scraper rows=1 mapped=0 /  |
| C07 | العمق والسقف لكل استعلام | ✅ PASS | requested 5, received 5 in 19.4s. Documented ceiling: ~$1.50-2.70 / 1,000 results as of Nov 2026. |
| C08 | التصفية الزمنية | ✅ PASS | onlyPostsNewerThan on the scraper |
| C09 | سلوك واضح عند الفشل | ✅ PASS | empty/failed result reported explicitly as 'error' with reason 'actor=apify~instagram-scraper returned 1 marker row(s) and no content: error=no_items. The' - no silent success |
| C10 | التكلفة مقاسة فعلياً | ✅ PASS | measured $0.0267 for 5 item(s) = $5.34 per 1,000 |
| C11 | الوصول للجمهور السعودي/العربي | ✅ PASS | 5/5 sampled items are Arabic (100%) |

### x

- **التكلفة المقاسة:** $0.0
- status=error reason=actor=apidojo~tweet-scraper returned 10 marker row(s) and no content: noResults=True. The actor reached no results for this query (upstream block, quota, or genuinely nothing matching).

| # | المعيار | الحالة | الدليل |
|---|---|---|---|
| C01 | البحث بالعربية يُرجع نتائج | ❌ FAIL | search failed: error - actor=apidojo~tweet-scraper returned 10 marker row(s) and no content: noResults=True. The actor reached no results for this query (upstream block, quota, or gen |
| C02 | جلب تعليقات المستخدمين لا الأوصاف فقط | ❓ UNTESTED | no items to inspect |
| C03 | كل عنصر له رابط مصدر | ❓ UNTESTED | no items to inspect |
| C04 | اسم المؤلف وتاريخ النشر محفوظان | ❓ UNTESTED | no items to inspect |
| C05 | مقاييس التفاعل (مشاهدات/إعجابات/تعليقات/مشاركات) | ❓ UNTESTED | no items to inspect |
| C06 | الردود على التعليقات متاحة | ⚠️ PARTIAL | the actor accepts conversationIds, so a thread can be pulled, but threading is not wired into the connector |
| C07 | العمق والسقف لكل استعلام | ❓ UNTESTED | requested 5, received 0 in 2.4s. Documented ceiling: Provider per-result billing. Official X alternative: pay-per-use, ~$0.005 per post read, no free tier (Nov 2026). |
| C08 | التصفية الزمنية | ✅ PASS | actor supports since/until via search operators |
| C09 | سلوك واضح عند الفشل | ✅ PASS | empty/failed result reported explicitly as 'error' with reason 'actor=apidojo~tweet-scraper returned 10 marker row(s) and no content: noResults=True. The ' - no silent success |
| C10 | التكلفة مقاسة فعلياً | ⚠️ PARTIAL | measured $0.0 for 0 item(s) |
| C11 | الوصول للجمهور السعودي/العربي | ❓ UNTESTED | no items to inspect |

## مفتاح الحالات

- ✅ **PASS** — مُثبت بدليل من تشغيل حقيقي
- ⚠️ **PARTIAL** — يعمل جزئياً أو القدرة موجودة ولم تُفعّل في هذا الفحص
- ❌ **FAIL** — لا يعمل، والسبب مذكور
- ➖ **NA** — لا ينطبق على هذه المنصة
- ❓ **UNTESTED** — لم يُشغَّل؛ **لا يُحسب نجاحاً**

## التكلفة المقاسة فعلياً (C10)

- أُنفق خلال هذا التحقق: **$0.1125**
- عناصر مجلوبة: **166**
- **التكلفة لكل ١٠٠٠ عنصر: $0.678**
