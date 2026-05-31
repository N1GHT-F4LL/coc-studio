# Clash of Clans — Feature Breakdown & Automation Gap Analysis

> **Khung tham chiếu (đọc trước):** coc-studio **không** phải bản clone của CoC. Nó là một
> **công cụ automation** lái game CoC *thật* qua ADB + computer-vision + OCR. Vì vậy tài liệu
> này **không** chấm "đã dựng lại tính năng game chưa", mà chấm **"bot tự động hoá được tính
> năng đó tới đâu"**. Các mảng như defense balancing, monetization, backend services, anti-cheat
> thuộc về *làm ra game* → với coc-studio chúng là **N/A (out of scope by design)**, không phải "missing".
>
> **Số liệu game cụ thể** (cost/time/DPS/level-cap từng cấp) **không** được liệt kê ở đây — đó là
> live data đổi theo mỗi update. Tài liệu cho **cấu trúc + cơ chế**; số chính xác tra
> `clashofclans.fandom.com` hoặc Supercell official. (Nguyên tắc: không bịa số liệu.)
>
> **Phương pháp (theo yêu cầu):** Phase 1 (chức năng game hiện tại) **đối chiếu bằng web search**
> (Wiki + Supercell release notes, 2026) — xem [Nguồn web](#nguồn-web-2026). Phase 2 (tool cover được gì)
> **suy trực tiếp từ code** (33 block / 4 screen / 5 graph), không theo trí nhớ.
> Ngày: 2026-05-31. Game ở mốc **Town Hall 18** (Feb 2026 update).

Ký hiệu coverage: ✅ Implemented · 🟡 Partial · ⛔ Missing · ⚪ N/A (out of scope)

---

## Phase 1 — Feature Breakdown Structure (CoC), chú thích theo góc automation

Với mỗi mảng: liệt kê sub-feature + **A:** = mức độ *liên quan tới automation* và lý do. Số liệu → wiki.

### 1. Account & Player Profile
Account creation · Login · Save/cloud sync · Multi-device · Account recovery · Player profile ·
Statistics · Achievements display · Name change · Player tags · Friends · Block list · Online status · Activity.
- **A:** ⚪ Hầu hết out-of-scope. Bot vận hành trên **một thiết bị đã đăng nhập sẵn**. Tự động tạo
  tài khoản / recovery là rủi ro ToS và không phải mục tiêu. *Có ích về sau:* đọc statistics/loot
  từ profile để log tiến độ (OCR) — nhưng đó là "đọc", không phải quản lý account.

### 2. Village System
**2.1 Buildings** (mỗi building có: purpose · upgrade levels · cost · duration · unlock cond · dependencies — số → wiki):
Town Hall (**max TH18**, weapon Giga Inferno → Inferno Artillery → ở TH18 thay bằng **Guardians**) ·
Builder Hut · Clan Castle · Laboratory · Army Camp · Barracks · Dark Barracks ·
Spell Factory · Dark Spell Factory · Workshop · Pet House · **Blacksmith** · Forge · Hero Hall · + toàn bộ
resource buildings (mines/collectors/drills), storages, walls, traps.
**Building-merge system (TH16→17):** defense max phải **merge** (Cannon→Ricochet Cannon, Archer Tower→Multi-Archer
Tower, Geared Cannon+Geared Archer Tower→Multi-Gear Tower, Eagle+Giga Inferno→Inferno Artillery, Wizard Tower→Super Wizard Tower).
- **A:** ⛔ coc-studio chưa có **building-upgrade loop** (chạm building → Upgrade → confirm → trừ
  tài nguyên). Có sẵn primitives (`tap`, `tap_template`, `find_template`, OCR) để dựng, nhưng thiếu:
  builder-availability detection, đọc cost vs tài nguyên hiện có, chọn build tiếp theo.

**2.2 Resources:** Gold · Elixir · Dark Elixir · Gems · Raid Medals · League Medals · Capital Gold ·
Event Currency — mỗi loại: source / storage / usage / limits / overflow.
- **A:** 🟡 **Gold/Elixir/Dark: thu được** (`collect_resources`). **Gems / Raid Medals / League Medals /
  Capital Gold / Event currency: ⛔** (chưa đọc, chưa tiêu). Treasury / overflow handling: ⛔.

### 3. Building Upgrade System
Queue · builder assignment · concurrent upgrades · cancellation · upgrade boost · cost calc ·
time reduction · magic-item interaction.
- **A:** ⛔ Toàn bộ missing. Đây là **automation loop lớn thứ 2** (đóng vòng kinh tế: thu → tiêu).
  Phụ thuộc: builder-free detection + per-building upgrade flow + cost OCR.

### 4. Troop / Army System
Normal · Dark · Super troops; mỗi troop: stats · housing space · unlock · upgrade path · AI ·
target preference · special ability. **Quân sự (army management):** train ở Barracks/Dark Barracks,
hàng đợi training, quick-train army, đổ đầy Army Camp, "army ready" detection.
- **A:** 🟡/⛔ coc-studio **thả** quân (deploy) nhưng **không train** quân. Thiếu: training queue,
  brew spell, kiểm tra camp đầy trước khi đánh. → Đây là **gap chặn unattended farming** (hiện
  `deploy` ngầm giả định quân đã sẵn). Stats/AI từng troop = kiến thức game, không cần model trong bot.

### 5. Hero System
**6 hero (2026):** Barbarian King · Archer Queen · Grand Warden · Royal Champion · **Minion Prince** (TH17, 11/2024) ·
**Dragon Duke** (TH18, 02/2026). Quản lý ở **Hero Hall**. Mỗi hero: ability · upgrade mechanics · equipment · pets · AI · respawn.
- **A:** 🟡 *Thả* hero trong trận = một phần của `deploy`/scenario (Partial — tùy scenario có hero
  hay không). *Upgrade hero, kích ability đúng thời điểm, respawn-wait* = ⛔.

### 6. Equipment System (Hero Equipment — thay hệ "Hero Ability" cũ)
Mỗi hero lắp 2 equipment; nâng ở **Blacksmith** (TH8) bằng 3 loại **Ore**: Shiny / Glowy / Starry
(kiếm từ Star Bonus, Clan Wars, CWL, Clan Games, Season Pass). Common/Epic rarity · loadout management ·
**Prospector** (helper, TH10+) đổi Ore/ngày. Upgrade ở Blacksmith **tức thời** (chỉ tốn Ore).
- **A:** ⛔ Quản lý/loadout/upgrade equipment + đổi Ore chưa có. Khi đánh, equipment đi theo hero đã set sẵn ngoài bot.

### 7. Pet System
**12 pet (2026):** L.A.S.S.I · Electro Owl · Mighty Yak · Unicorn · Frosty · Diggy · Poison Lizard · Phoenix ·
Spirit Fox · Angry Jelly · Sneezy · **Greedy Raven** (Pet House lv12, TH18). Unlock · upgrade · assign 1-pet-1-hero · combat.
- **A:** ⛔ Assignment/upgrade pet chưa có (cấu hình thủ công ngoài bot).

### 8. Spell System
Mỗi spell: effect · radius · duration · targeting · upgrade. **Brewing** ở Spell Factory / Dark Spell Factory.
- **A:** 🟡/⛔ Thả spell = một phần scenario deploy (Partial). **Brew spell tự động = ⛔** (cùng nhóm "army management" §4).

### 9. Siege Machine System
Deployment rules · capacity · AI · unlock path (Workshop).
- **A:** 🟡 Thả siege = part of scenario deploy. Build siege ở Workshop = ⛔.

### 10. Combat System ⭐ (trọng tâm hiện tại của coc-studio)
**10.1 Attack flow:** matchmaking · search cost · opponent selection · shield interaction · revenge.
- **A:** ✅ `find_match` — bấm Attack → Find a Match → **OCR loot** → **skip base dưới ngưỡng**
  (`settings.farm`) tới khi gặp base đạt. Revenge/shield: ⛔ (chỉ next-match loop).

**10.2 Battle:** deployment rules · unit AI · pathfinding · target acquisition · damage calc ·
destruction % · star calc.
- **A:** ✅ `deploy` — thả quân theo **scenario đã migrate** (vd `Thrower`) qua đúng `_slot_deploy`
  topo-order, hoặc theo `settings`. AI/pathfinding/damage là *của game* (bot không tính), nhưng bot
  *điều khiển* việc thả. Đọc destruction%/sao realtime giữa trận: ⛔.

**10.3 Battle results:** loot calc · trophy ± · bonus · replay.
- **A:** 🟡/⛔ `read_loot` đọc loot **của địch trước khi đánh** (để quyết định đánh/bỏ). **Parse màn
  kết quả sau trận** (sao đạt, loot thực thu, trophy, "Return Home vs Next"): ⛔ → gap cho thống kê & quyết định.

**10.4 Return:** ✅ `return_home` — chờ trận xong → Return Home → đóng popup.

### 11. Defense System
Cannon · Archer Tower · Mortar · Wizard Tower · Air Defense · Inferno · Eagle Artillery · Monolith ·
Spell Tower (có tùy chọn **EQ Spell Tower**, 02/2026) · X-Bow · Scattershot · và **defense mới TH17/18:**
**Firespitter** (aimed, cone), **Inferno Artillery** (TH-weapon TH17), merged: **Ricochet Cannon / Multi-Archer
Tower / Multi-Gear Tower / Super Wizard Tower**, **Revenge Tower**, **Guardians** (Smasher/Longshot — TH18 thay TH-weapon),
Crafted Defenses; trap mới **Giga Bomb**. Mỗi cái: targeting · damage · range · upgrade · special.
- **A:** ⚪ Phần lớn N/A — bot là bên **tấn công**, không "quản lý" defense. *Layout editing / base
  design* = ⛔ (chưa làm, ít ưu tiên). *Nhận diện defense khi scout để chọn base* = ⛔ (nâng cao).

### 12. Clan System
Creation · roles · permissions · join requests · settings · bookmarks · recommendations · chat ·
mail · labels · **donate/request troops**.
- **A:** 🟡 `request_clan_troops` (xin quân ở màn chuẩn bị, nếu nút hiện). **Donate, chat, join/leave,
  settings: ⛔.** Auto-donate là automation có giá trị (raid medals/clan games) → roadmap.

### 13. Clan War System
War search · matchmaking · prep day · battle day · attack allocation · scoring · rewards · war logs.
- **A:** ⛔ 0%. Cả một **automation track riêng** (war map screen + chọn target + attack flow — *tái dùng
  được* find/deploy/return primitives + scenario engine).

### 14. Clan War League (CWL)
Group generation · ranking · promotion/demotion · rewards.
- **A:** ⛔ 0% (mở rộng của §13; lịch nhiều ngày → cần scheduling).

### 15. Clan Capital
Districts · capital upgrades · raid weekends · Capital Gold · Raid Medals · matchmaking · reward calc.
- **A:** ⛔ 0%. Map + cơ chế tách biệt (raid weekend loop riêng).

### 16. Builder Base (2.0)
Buildings · resources · troops · **Battle Copter** (hero mới, thay Battle Machine) · star bonus · progression
(**max Builder Hall 10**). **Builder Base 2.0 đã bỏ versus battle** → đánh tự do, **multi-stage**: Builder Base
district → (BH6+) **O.T.T.O's Outpost**, tối đa 6 sao.
- **A:** ⛔ 0%. **Base thứ hai hoàn toàn** — cần screen-detection + deploy loop riêng cho **multi-stage attack** (không còn versus).

### 17. Economy System
Resource generation · loot formulas · loot protection · treasury · shop · offers · event rewards · trader.
- **A:** 🟡 Bot **quan sát** loot (`read_loot`, loot threshold trong `find_match`) nhưng không model
  formula. **Shop / offers / trader / treasury collect: ⛔.**

### 18. Magic Item System
Books · Hammers · Potions · Runes · Shovels (apply để skip time/cost).
- **A:** ⛔ Dùng magic item tự động (vd Book of Building khi xong research): chưa có. Cùng nhóm upgrade automation.

### 19. Achievement System · 20. Event System · 21. Gold/Event Pass
Achievements (defs/rewards/progress) · seasonal events/temp troops/temp currency/challenges · pass free+premium track / claims.
**Gold Pass rework (02/2026):** Season Bank → **Hoggy Bank** (full size ngay, Gold Pass cho **5× payout** khi claim cuối mùa).
- **A:** ⛔ Claim reward / progress pass tự động: chưa có. *Ít ưu tiên* (giá trị thấp so với farm/upgrade loop), nhưng "auto-claim" là tiện ích nhỏ dễ thêm bằng primitives.

### 22. Social · 23. Notification System
Friends/recommend/share/replay/spectate/recruit · notifications (builder done / army ready / war attack / event end).
- **A:** ⚪/⛔ Social phần lớn out-of-scope. **Notification CỦA BOT** (không phải của game) thì coc-studio
  *đã có* kênh riêng: Run console + WS event stream. *Đọc* notification của game để trigger (vd "army ready")
  = ý tưởng nâng cao.

### 24. Monetization · 25. Backend Systems
Gems/packages/offers/passes/cosmetics · Auth/Player/Economy/Combat/Matchmaking/Clan/Chat/Replay/Event/Analytics/Anti-cheat/LiveOps services.
- **A:** ⚪ **Hoàn toàn out-of-scope.** Đây là việc *Supercell vận hành game*. coc-studio là client
  automation; nó **không** có (và không nên có) backend game, monetization hay anti-cheat. Liệt kê ở
  đây chỉ để đánh dấu rõ ràng "không thuộc phạm vi", tránh nhầm là "thiếu".

---

## Phase 2 — Hiện trạng coc-studio (suy từ code)

**Engine (nền tảng, đã có):** block-graph dataflow executor (topo-order, control + typed-data edges),
registry typed-port (`Coord/Number/Template/Region/Bool/Text/Trigger`), validate + cycle guard,
fail-stop error model, WebSocket run streaming, RuntimeContext bọc các singleton reuse từ `core/` + `screens/`.

**Screens đang dùng (4):** `base_screen`, `home_screen`, `attack_screen`, `battle_screen`.
→ **Thiếu screen cho:** army/training, building-upgrade, lab, clan war map, clan capital, builder base.

**33 block hiện có:**

| Nhóm | Block |
|---|---|
| CoC | `ensure_home`, `collect_resources`, `find_match`, `deploy`, `return_home`, `request_clan_troops` |
| Control | `delay`, `if`, `loop_n`, `loop_until` |
| Vision | `wait_template`, `is_screen`, `find_template`, `is_home`, `is_attack`, `is_battle` |
| Input | `tap`, `tap_template`, `swipe_line`, `pinch` |
| OCR | `read_number`, `read_loot`, `loot_ge` |
| Logic | `const_number`, `const_bool`, `compare`, `logic_and`, `logic_or`, `logic_not` |
| Util | `log`, `close_popups`, `restart_game`, `set_flag` |

**Graph mẫu (5):** `farm_cycle`, `farm_loop`, `Thrower_farm`, `find_tap`, `if_demo`.

**Kết luận hiện trạng:** coc-studio đã hoàn chỉnh **một loop**: *farming attack* (ensure home → collect →
find match có loot-OCR-skip → deploy theo scenario → return → recovery). Ngoài loop đó, gần như mọi
gameplay loop khác chưa được tự động hoá — **nhưng engine + primitives đủ tổng quát để biểu diễn phần lớn chúng.**

---

## Phase 3 — Coverage Matrix

| # | CoC area | Status | coc-studio có gì | Gap chính |
|---|---|---|---|---|
| 1 | Account/Profile | ⚪ | — | Out of scope (thiết bị đăng nhập sẵn) |
| 2 | Resources — collect (gold/elixir/dark) | ✅ | `collect_resources` | gems/medals/capital gold; treasury; gembox/obstacle |
| 3 | Buildings & upgrade loop | ⛔ | chỉ primitives `tap`/`find_template`/OCR | builder-free detect, upgrade flow, cost check |
| 4 | Building upgrade system (queue/boost) | ⛔ | — | toàn bộ |
| 5 | Army — train/brew/fill | ⛔ | — | training queue, brew, "army ready" → **chặn unattended** |
| 6 | Combat — find match | ✅ | `find_match` + loot OCR + skip | revenge/shield, chọn base nâng cao |
| 7 | Combat — deploy | ✅ | `deploy` (scenario / settings) | thả hero ability/timing realtime |
| 8 | Combat — return | ✅ | `return_home` | — |
| 9 | Combat — battle results parse | ⛔ | `read_loot` chỉ đọc loot **địch trước trận** | parse sao/loot-thực-thu/trophy sau trận |
| 10 | Heroes/Equipment/Pets — manage/upgrade | ⛔ | thả qua scenario | upgrade, loadout, assign |
| 11 | Spells/Siege — build | ⛔ | thả qua scenario | brew/build |
| 12 | Clan — request troops | 🟡 | `request_clan_troops` | donate, chat, join/leave, settings |
| 13 | Clan War | ⛔ | — | war map + attack allocation loop |
| 14 | CWL | ⛔ | — | + scheduling nhiều ngày |
| 15 | Clan Capital | ⛔ | — | raid weekend loop, map riêng |
| 16 | Builder Base | ⛔ | — | base + versus loop riêng |
| 17 | Economy — shop/offers/trader/treasury | ⛔ | quan sát loot | claim/buy |
| 18 | Magic items | ⛔ | — | auto-apply |
| 19–21 | Achievements/Events/Pass | ⛔ | — | auto-claim (ưu tiên thấp) |
| 22 | Social | ⚪ | — | out of scope |
| 23 | Notifications (của game) | ⛔ | (bot có Run console riêng) | đọc noti game để trigger (nâng cao) |
| 24–25 | Monetization / Backend / Anti-cheat | ⚪ | — | out of scope by design |

---

## Phase 4 — % Completion (ước lượng, có nhãn)

> Đây là **ước lượng theo "bề mặt gameplay tự động hoá được"**, không phải đo chính xác. Mẫu số rất
> quan trọng — xem hai cách đo.

**Theo từng loop:**

| Loop / mảng | Coverage ước lượng |
|---|---|
| Farming attack loop (find/deploy/return) | ~80% |
| Resource collection | ~65% (thiếu gems/medals/treasury) |
| Recovery/robustness (ensure_home, restart, close_popups) | ~60% |
| Army management (train/brew) | ~5% |
| Building/lab/hero upgrades | ~3% |
| Clan (donate/request) | ~15% |
| Clan War / CWL / Capital / Builder Base | 0% |
| Economy meta (shop/trader/pass/events) | 0% |

**Theo hai mẫu số:**
- So với **toàn bộ gameplay loops tự động hoá được**: **~20–25%**.
- So với **loop đã chọn làm (farming)**: **~75–80%** (đã trưởng thành, chạy thật end-to-end).
- So với **toàn bộ feature của game** (kể cả phần out-of-scope): mẫu số sai → con số vô nghĩa, **không dùng**.

**Thông điệp chiến lược:** coc-studio không "hoàn thành 20% game" — nó đã **làm xong 1 loop gần trọn vẹn**.
Câu hỏi đúng không phải "tăng % phủ" mà là **"loop tiếp theo đáng tự động hoá là cái nào"**.

---

## Phase 5 — Gap tiers (diễn giải lại cho sản phẩm automation)

| Tier | Định nghĩa cho coc-studio | Còn thiếu gì để đạt |
|---|---|---|
| **MVP** ✅ đã đạt | Chạy 1 farm cycle trọn vẹn trên device thật | (đã có: ensure_home → collect → find_match → deploy → return) |
| **Alpha gap** | **Unattended farming nhiều giờ** không cần người trông | (a) army training loop (đổ đầy quân giữa các trận), (b) battle-result parse, (c) recovery cứng hơn + detect disconnect/maintenance, (d) scheduling/loop dài hạn |
| **Beta gap** | **Tự tiến hóa base** (progression) | (e) building-upgrade automation (builder-free detect + cost OCR), (f) lab/hero/equipment upgrade, (g) auto-donate + magic-item apply |
| **Production gap** | **Multi-mode + multi-account + observability** | (h) Clan War/CWL attack, (i) Clan Capital raid, (j) Builder Base, (k) multi-account orchestration, (l) stats dashboard + alerting, (m) preset/profile config, headless reliability |

---

## Phase 6 — Roadmap theo thứ tự phụ thuộc kỹ thuật

Nền tảng đã sẵn (engine block-graph, primitives tap/find/OCR/control-flow, screen detection, scenario deploy).
Các bước sau xếp theo **dependency**, không theo "độ hot".

1. **Battle-result parsing** *(nhỏ, mở khoá nhiều thứ)* — screen "battle end" + OCR sao/loot-thực-thu →
   output block mới. Phụ thuộc: OCR (có) + 1 screen detection mới. → cải thiện quyết định farm + nền cho stats.
2. **Army management loop** *(chặn Alpha)* — screen Army/Barracks + block `train_army`/`check_army_ready`/`brew_spells`.
   Phụ thuộc: screen mới + tap/find (có). → biến farm thành **unattended thật sự**.
3. **Robust scheduling & recovery** — time-based trigger + detect disconnect/maintenance/ad-popup; mở rộng
   `loop_until`/`set_flag` (có) + util. Phụ thuộc: #1/#2 để biết khi nào "rảnh". → hoàn tất **Alpha**.
4. **Building-upgrade loop** *(chặn Beta)* — screen building + builder-free detect + cost OCR vs tài nguyên +
   block `upgrade_building`/`builders_free`. Phụ thuộc: OCR + screen mới. → đóng vòng kinh tế (thu→tiêu).
5. **Lab / Hero / Equipment upgrade + Auto-donate + Magic-item apply** — mở rộng #4 sang các màn tương ứng. → hoàn tất **Beta**.
6. **Clan War attack loop** — war-map screen + chọn target + **tái dùng** find/deploy(scenario)/return. Phụ thuộc: scenario engine (có) + screen war map.
7. **Clan Capital raid loop** — map + district + deploy riêng (tái dùng deploy core).
8. **Builder Base 2.0 multi-stage loop** — base + troop/deploy riêng (versus đã bỏ; xử lý 2 stage: district → O.T.T.O's Outpost).
9. **Cross-cutting (Production):** multi-account orchestration, stats dashboard + alert, preset/profile, headless reliability.

**Đường tới hạn (critical path) cho "bot farm chạy 24/7 tự lo quân + tự nâng cấp":** #1 → #2 → #3 → #4.
Bốn bước này biến coc-studio từ "chạy 1 cycle" thành "vận hành làng gần như tự trị" — đáng ưu tiên hơn
mở rộng sang War/Capital/Builder Base (mỗi cái là một track lớn, giá trị/độ-khó tùy mục tiêu của bạn).

---

## Nguồn web (2026)
Phase 1 đối chiếu bằng web search (trạng thái game 05/2026). Số liệu cụ thể từng level tra trực tiếp các nguồn này:
- [Town Hall — CoC Wiki](https://clashofclans.fandom.com/wiki/Town_Hall) · [TH18 update — Supercell](https://supercell.com/en/games/clashofclans/blog/release-notes/town-hall-18-crash-lands-update/)
- [Minion Prince — Wiki](https://clashofclans.fandom.com/wiki/Minion_Prince) · [All hero levels 2026](https://gameboost.com/blog/all-clash-of-clans-hero-levels)
- [Hero Equipment — Wiki](https://clashofclans.fandom.com/wiki/Hero_Equipment) · [Blacksmith & Ore — Supercell Support](https://support.supercell.com/clash-of-clans/en/articles/hero-equipment-ore-4.html) · [Version History 2026 — Wiki](https://clashofclans.fandom.com/wiki/Version_History/2026)
- [Pets — Wiki](https://clashofclans.fandom.com/wiki/Pets) · [Greedy Raven — Wiki](https://clashofclans.fandom.com/wiki/Greedy_Raven) · [Feb 2026 update](https://supercell.com/en/games/clashofclans/blog/release-notes/the-february-update-has-escaped/)
- [TH17 update (defenses) — Supercell](https://supercell.com/en/games/clashofclans/blog/game-updates/the-town-hall-17-update-is-here-2/)
- [Builder Hall — Wiki](https://clashofclans.fandom.com/wiki/Builder_Hall) · [Builder Base 2.0 guide](https://theriagames.com/guide/clash-of-clans-builder-base-2-0-guide/)

## Lưu ý
- **Không bịa số liệu game** (cost/time/DPS/level) — dùng nguồn trên; tài liệu này chỉ cho cấu trúc + cơ chế.
- Trạng thái coc-studio: suy trực tiếp từ `backend/blocks/`, `backend/screens/`, `backend/data/graphs/` (2026-05-31).
- Automation game có thể vi phạm ToS của game — đây là đánh giá tính năng/kỹ thuật, không phải khuyến nghị vận hành.
- Muốn map theo **danh sách feature do bạn tự cung cấp** (khác với suy-từ-code), hoặc muốn bản FBS *game-design literal* (để dựng clone), gửi yêu cầu — đây là bản theo lens **automation coverage**.
