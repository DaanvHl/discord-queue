# Team-Picking Strategies — Proposal (revised)

After your feedback, the shortlist is **three** picking methods, selectable per match:

1. **Snake Draft** — captains draft, fixed to a real snake. ✅ *Done (now live).*
2. **Random Teams (with reroll)** — instant shuffle, reroll if lopsided. *To build.*
3. **Auction / Bidding** — coin budget, bid on players. *To build.*

Dropped per your call: Auto-Balance (rating is skewed by games played, not just skill),
Straight Alternating, Tiered Draft, Blind/Sealed-Bid.

---

## 1. Snake Draft ✅ (fixed)

Now a **true snake**: the first-pick captain starts, then the order reverses every round —
**A, B, B, A, A, B, B, A, …** — instead of the old "second captain gets 2 only when 3 remain."
Teams always come out even; the last player is auto-assigned to whichever team is next in the
order (no pointless final pick). This is what's running now.

---

## 2. Random Teams (with reroll)

The bot shuffles everyone into two random teams and shows them. A **Reroll** button lets the
group redo the split if it looks unfair, as many times as they want. Fast, no drama.

**Open questions for you:**
- **Who can reroll?** Options: (a) either captain, (b) anyone in the match, (c) a majority vote.
  Simplest is either captain.
- **Reroll limit?** Unlimited, or cap it (e.g. 5) so it can't be spammed forever?
- Should we still show each team's **average rating** just as info (not used to balance, just so
  people can eyeball it), or hide ratings entirely?

**Build effort:** Low.

---

## 3. Auction / Bidding Draft

Each captain gets a **coin budget**. The bot goes through the players; captains bid; highest
bidder wins and pays. When one team is full, the rest fill the other team.

Rules I'll bake in (from the last doc): a **reserve rule** so you always keep ≥1 coin per empty
slot (can't leave your team short), ties broken toward the team with **fewer players**, and
no-bid players going to the emptier team for cheap/free.

**Three calls I need from you:**
- **Budget:** 100 coins (finer bids) or 20 (simpler)?
- **Player order:** random, or **best-rated first** (forces early spending on stars — more fun)?
- **Style:** **List** (auction each player in order — your original idea) or **Nomination**
  (captains take turns putting a player up for bid — more strategic)?

**Build effort:** High.

---

## The one cross-cutting decision: how is the method chosen?

- **(A) Button each match** — after captains lock in, a prompt: "Pick teams how? 🎲 Random ·
  📋 Snake · 💰 Auction". The group decides per game. *(My recommendation — most flexible.)*
- **(B) Per-channel default** — an organizer sets the method for a channel with a command; every
  match there uses it.
- **(C) Both** — a channel default, overridable by the button.

---

### So, to move forward I need:
1. **Selection:** A, B, or C above?
2. **Random:** who can reroll + any limit?
3. **Auction:** budget (100/20), order (random/best-first), style (list/nomination)?

Answer those and I'll build Random first (quick), then Auction.
