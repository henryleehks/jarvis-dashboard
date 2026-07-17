// J.A.R.V.I.S. command center — data feed.
// Swap these values (or fetch them into this shape) to repoint the dashboard at real data.
window.JARVIS_DATA = {
  greeting: "Good evening, Henry.",
  generated: "16 JUL 2026 · 23:29:43",

  connectors: [
    { name: "GMAIL",      status: "online"  },
    { name: "CALENDAR",   status: "online"  },
    { name: "STRIPE",     status: "online"  },
    { name: "ANALYTICS",  status: "offline" },
    { name: "SLACK",      status: "online"  },
    { name: "GITHUB",     status: "offline" }
  ],

  content: {
    funnel: [
      { label: "REACH",       value: 128400, max: 150000, unit: ""  },
      { label: "SIGNUPS",     value: 5807,   max: 8000,   unit: ""  },
      { label: "TRIALS",      value: 23,     max: 40,     unit: ""  },
      { label: "CONVERSIONS", value: 96,     max: 120,    unit: ""  },
      { label: "MRR",         value: 9868,   max: 10000,  unit: "$" }
    ]
  },

  sponsors: [
    "STARK INDUSTRIES",
    "OSCORP",
    "WAYNE ENTERPRISES",
    "CYBERDYNE SYSTEMS",
    "UMBRELLA CORP"
  ],

  priorities: [
    "Reply to the Oscorp contract — it's held up legal review for two days.",
    "Approve the Wayne Enterprises sponsor invoice, $932 due.",
    "Check the ANALYTICS connector once it reconnects — churn spike unread since 21:04.",
    "Confirm tomorrow's 09:00 sync with the Stark Industries account lead."
  ],

  headline: {
    label: "PRIMARY OBJECTIVE",
    target: 10000,
    current: 9868,
    due: 932,
    figures: [
      { label: "MRR",  value: "$9,868"  },
      { label: "GOAL",  value: "$10,000" },
      { label: "DUE",  value: "$932"    }
    ]
  },

  closer: "That's everything that needs your attention, sir. I'll keep watch on the rest."
};
