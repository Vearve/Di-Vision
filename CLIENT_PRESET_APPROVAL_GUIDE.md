# Client Preset Approval Process - Complete Guide

## Overview
Clients can now review and approve/reject presets submitted by contractors. The approval workflow is fully integrated into the frontend with no need for Django admin.

---

## How Clients Access the Approval Interface

### 1. **Navigate to Preset Approvals**
   - Clients log in to their account
   - In the navbar, click **"Preset Approvals"** (visible to client users only)
   - OR navigate directly to `/presets/approval/`

### 2. **Dashboard Structure**
The Preset Approvals dashboard shows:

```
┌─────────────────────────────────────────────────────────────┐
│ Preset Approvals                                            │
│ Review and approve presets submitted by contractors         │
│                                            3 Pending Approval│
├─────────────────────────────────────────────────────────────┤
│                                                              │
│ ⏳ PENDING APPROVALS (Waiting for Your Review)              │
│                                                              │
│ 🔧 Drill Size Services (2)                          PENDING │
│ ├─ Standard Drilling Service      Contractor A   $100/meter │
│ │  [Review & Approve] [View Details]                        │
│ └─ Deep Well Drilling             Contractor B   $150/meter │
│    [Review & Approve] [View Details]                        │
│                                                              │
│ ⚙️ Equipment (1)                                     PENDING │
│ ├─ Drilling Rig                   Contractor A   $500/day   │
│    [Review & Approve] [View Details]                        │
│                                                              │
│ 📦 Consumables (0)                                  PENDING │
│ (No pending consumable presets)                             │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│ ✅ APPROVED PRESETS (Locked & Ready to Use)                │
│                                                              │
│ 🔧 Drill Size Services (1)                       APPROVED  │
│ ├─ Basic Drilling Service         Contractor C   $80/meter │
│    [Locked]                                                 │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Step-by-Step Approval Process

### Step 1: Review Pending Presets
1. Open Preset Approvals dashboard
2. See all pending presets grouped by type (Drill Size, Equipment, Consumables)
3. Review the rates and contractor information

### Step 2: Click "Review & Approve"
1. Click the blue **[Review & Approve]** button next to a preset
2. Opens the detailed preset page with full information:
   - Preset name
   - Contractor workspace
   - Proposed rate and unit
   - Status indicators

### Step 3: Make Your Decision
On the detail page, you'll see an "Client Approval" card on the right side:

```
┌─────────────────────────┐
│ Client Approval         │
├─────────────────────────┤
│ Approve or reject this  │
│ preset submission.      │
│                         │
│ Decision:               │
│ [Choose...        ▼]     │ ← Select Approve or Reject
│                         │
│ Comments:               │
│ [Type your notes...]    │ ← Optional: explain your decision
│                         │
│ [Submit Decision ✓]     │ ← Click to confirm
└─────────────────────────┘
```

### Step 4A: Approve the Preset
1. Click the **Decision** dropdown
2. Select **"Approve"**
3. (Optional) Add comments in the Comments field
   - Example: "Rate approved. Please proceed."
4. Click **[Submit Decision]**
5. Preset status changes to **APPROVED** ✅
6. Rate is now **LOCKED** (cannot be changed)
7. Available for use in BOQ reports

### Step 4B: Reject the Preset
1. Click the **Decision** dropdown
2. Select **"Reject"**
3. Add comments explaining the rejection
   - Example: "Rate is higher than our budget. Please resubmit at $90/meter."
4. Click **[Submit Decision]**
5. Preset status changes to **REJECTED** ❌
6. Contractor receives notification and can resubmit

---

## Important Features

### 🔒 Rate Locking
- Once YOU (the client) approve a preset, the rate becomes **LOCKED**
- Contractors CANNOT change it after approval
- This ensures cost consistency in BOQ reports
- Locked rates appear with a **"Locked"** badge

### 📋 Pending vs. Approved Sections
The dashboard shows two clear sections:

| **PENDING APPROVALS** | **APPROVED PRESETS** |
|---|---|
| Waiting for your review | Already approved and locked |
| Show ⏳ badge | Show ✅ badge |
| Have [Review & Approve] button | Show [Locked] badge |
| Count displayed prominently | Listed for reference |

### 📊 Quick Summary
- **Pending Counter**: Badge at top shows number of presets awaiting approval
- **Contractor Name**: See which contractor submitted each preset
- **Rate Information**: Clear display of proposed rates and units
- **Submission Date**: When the preset was submitted

---

## What Happens Next (After Approval)

### When You Approve a Preset:
1. ✅ Preset becomes **APPROVED** and **LOCKED**
2. 📧 Contractor is notified
3. 💾 Moves to "Approved Presets" section in your dashboard
4. 📋 Available for the contractor to use in BOQ creation
5. 💰 Rates automatically populate BOQ line items

### When You Reject a Preset:
1. ❌ Preset status becomes **REJECTED**
2. 📧 Contractor receives notification with your comments
3. ⚠️ Contractor can edit and resubmit with new rates
4. 📋 Goes back to pending for re-review

---

## Common Scenarios

### Scenario 1: Fast Approval ✅
```
Contractor submits: "Standard Drilling Service" at $100/meter
You review: Rates are within budget
Action: Click Approve (no comments needed)
Result: Immediately available for BOQ use
Time: 2 minutes
```

### Scenario 2: Conditional Approval
```
Contractor submits: "Drilling Rig" at $600/day
You review: Slightly high, but acceptable
Action: Click Approve + Comment: "Approved. Please confirm availability for Q2."
Result: Locked and ready, contractor sees your feedback
Time: 3 minutes
```

### Scenario 3: Negotiation Needed
```
Contractor submits: "Drilling Fluid" at $60/liter
You review: Out of budget (you typically pay $45/liter)
Action: Click Reject + Comment: "Rate too high. We negotiate at $45/liter. Please resubmit."
Result: Rejected, contractor resubmits at $45/liter
Later: You re-review and approve the $45/liter rate
Time: Full back-and-forth takes ~1 hour
```

---

## Key Points for Clients

✅ **DO:**
- Review presets carefully before approving
- Add clear comments when rejecting
- Approve presets you're comfortable with for BOQ use
- Reference approved rates in negotiations with contractors

❌ **DON'T:**
- Approve presets impulsively without review
- Leave rejection comments vague (be specific about objections)
- Forget that approved rates are LOCKED (discuss with contractor first)

---

## For Your Team

Share this information with your procurement/finance team:
- "Presets are like locked-in rates from contractors"
- "Approving a preset means we accept those rates for invoicing"
- "Rejected presets go back to the contractor for renegotiation"
- "All decisions are logged with timestamps and comments"

---

## Technical Notes

**Backend Workflow:**
1. Contractor creates preset (Draft status)
2. Contractor submits to your company → `client_status = PENDING`
3. You review → Approve/Reject
4. System records: decision, timestamp, client_approved_by, comments
5. Status updates to `APPROVED` or `REJECTED`
6. Available for BOQ selection if approved

**Database Fields Updated:**
- `client_status`: Changes from PENDING → APPROVED/REJECTED
- `client_approved_at`: Timestamp of approval
- `client_approved_by`: Your username
- `client_comments`: Your approval/rejection notes

---

**Questions?** Contact your IT support or the contractor directly if you need clarification on proposed rates.
