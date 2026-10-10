/* Static demo data. Times are hours from day 1, 00:00. Replace with live API data (see INTEGRATION.md). */
window.CARBON_DATA = {
 "meta": {
  "source": "Static demo data",
  "unit": "gCO2/kWh",
  "now": 15,
  "capacityKw": 8,
  "note": "Demo values on a synthetic grid profile. Not live data."
 },
 "series": {
  "forecast": [
   676,
   676,
   660,
   652,
   668,
   683,
   687,
   689,
   679,
   636,
   586,
   559,
   546,
   529,
   531,
   565,
   605,
   640,
   693,
   754,
   779,
   762,
   743,
   729,
   676,
   660,
   664,
   668,
   661,
   672,
   701,
   705,
   675,
   645,
   623,
   590,
   562,
   564,
   579,
   587,
   613,
   665,
   714,
   748,
   773,
   778,
   749,
   714,
   675,
   676,
   660,
   652,
   668,
   684,
   687,
   689,
   678,
   637,
   586,
   558,
   546,
   530,
   530,
   564,
   605,
   640,
   692,
   754,
   779,
   763,
   742,
   729
  ],
  "actual": [
   690,
   673,
   650,
   668,
   656,
   682,
   701,
   672,
   688,
   641,
   573,
   572,
   542,
   522,
   544
  ]
 },
 "jobs": [
  {
   "id": "urg-01",
   "type": "urgent_inference",
   "kw": 2.0,
   "dur": 1,
   "pad": 2,
   "sub": 9,
   "dl": 11,
   "base": 9,
   "start": 9,
   "state": "DONE",
   "forced": false,
   "infeasible": false,
   "gBase": 1282,
   "gOpt": 1282,
   "gBaseF": 1272,
   "gOptF": 1272,
   "reason": "Started right away: little slack, so no greener window was available.",
   "alts": [
    {
     "label": "Run now",
     "start": 9,
     "g": 2444
    },
    {
     "label": "Chosen",
     "start": 9,
     "g": 2444
    },
    {
     "label": "Latest feasible",
     "start": 9,
     "g": 2444
    }
   ]
  },
  {
   "id": "bat-02",
   "type": "batch_inference",
   "kw": 1.5,
   "dur": 2,
   "pad": 3,
   "sub": 8,
   "dl": 17,
   "base": 8,
   "start": 12,
   "state": "DONE",
   "forced": false,
   "infeasible": false,
   "gBase": 1994,
   "gOpt": 1596,
   "gBaseF": 1972,
   "gOptF": 1612,
   "reason": "Delayed 4 h to a cleaner window (538 vs 658 gCO2/kWh forecast). 3 h of slack remain.",
   "alts": [
    {
     "label": "Run now",
     "start": 8,
     "g": 2852
    },
    {
     "label": "Chosen",
     "start": 12,
     "g": 2409
    },
    {
     "label": "Latest feasible",
     "start": 14,
     "g": 2552
    }
   ]
  },
  {
   "id": "tra-03",
   "type": "training",
   "kw": 3.0,
   "dur": 4,
   "pad": 5,
   "sub": 7,
   "dl": 24,
   "base": 7,
   "start": 11,
   "state": "DONE",
   "forced": false,
   "infeasible": false,
   "gBase": 7722,
   "gOpt": 6540,
   "gBaseF": 7770,
   "gOptF": 6495,
   "reason": "Delayed 4 h to a cleaner window (541 vs 648 gCO2/kWh forecast). 9 h of slack remain.",
   "alts": [
    {
     "label": "Run now",
     "start": 7,
     "g": 9447
    },
    {
     "label": "Chosen",
     "start": 11,
     "g": 8190
    },
    {
     "label": "Latest feasible",
     "start": 19,
     "g": 11301
    }
   ]
  },
  {
   "id": "etl-04",
   "type": "etl",
   "kw": 1.0,
   "dur": 2,
   "pad": 3,
   "sub": 6,
   "dl": 36,
   "base": 6,
   "start": 12,
   "state": "DONE",
   "forced": false,
   "infeasible": false,
   "gBase": 1373,
   "gOpt": 1064,
   "gBaseF": 1376,
   "gOptF": 1075,
   "reason": "Delayed 6 h to a cleaner window (538 vs 688 gCO2/kWh forecast). 22 h of slack remain.",
   "alts": [
    {
     "label": "Run now",
     "start": 6,
     "g": 2055
    },
    {
     "label": "Chosen",
     "start": 12,
     "g": 1606
    },
    {
     "label": "Latest feasible",
     "start": 33,
     "g": 1858
    }
   ]
  },
  {
   "id": "tra-05",
   "type": "training",
   "kw": 2.5,
   "dur": 3,
   "pad": 4,
   "sub": 10,
   "dl": 30,
   "base": 10,
   "start": 11,
   "state": "DONE",
   "forced": false,
   "infeasible": false,
   "gBase": 4218,
   "gOpt": 4090,
   "gBaseF": 4228,
   "gOptF": 4085,
   "reason": "Delayed 1 h to a cleaner window (545 vs 564 gCO2/kWh forecast). 16 h of slack remain.",
   "alts": [
    {
     "label": "Run now",
     "start": 10,
     "g": 5550
    },
    {
     "label": "Chosen",
     "start": 11,
     "g": 5412
    },
    {
     "label": "Latest feasible",
     "start": 26,
     "g": 6662
    }
   ]
  },
  {
   "id": "my-06",
   "type": "training",
   "kw": 3.0,
   "dur": 3,
   "pad": 4,
   "sub": 15,
   "dl": 17,
   "base": 15,
   "start": 15,
   "state": "RUNNING",
   "forced": true,
   "infeasible": true,
   "gBase": 5436,
   "gOpt": 5436,
   "gBaseF": 5430,
   "gOptF": 5430,
   "reason": "No window fits before the deadline once the safety margin is added. Started at the earliest slot and flagged.",
   "alts": [
    {
     "label": "Run now",
     "start": 15,
     "g": 7509
    },
    {
     "label": "Forced start",
     "start": 15,
     "g": 7509
    },
    {
     "label": "Latest feasible",
     "start": 15,
     "g": 7509
    }
   ]
  }
 ],
 "kpi": {
  "forecasted": {
   "pct": 9.4,
   "jobs": 6,
   "baseG": 22048,
   "optG": 19969
  },
  "realized": {
   "pct": 12.2,
   "jobs": 5,
   "baseG": 16589,
   "optG": 14572
  },
  "deadlinesOptPct": 100,
  "deadlinesBasePct": 100,
  "waitOptH": 2.5,
  "waitBaseH": 0
 },
 "alerts": [
  {
   "id": 1,
   "level": "critical",
   "type": "sla risk",
   "time": 15,
   "job": "my-06",
   "msg": "my-06 cannot meet its deadline after the safety margin. Started at the earliest slot.",
   "ack": false
  },
  {
   "id": 2,
   "level": "info",
   "type": "replan",
   "time": 12,
   "job": "tra-05",
   "msg": "tra-05 start moved from D1 07:00 to D1 11:00 after a forecast update.",
   "ack": false
  },
  {
   "id": 3,
   "level": "warning",
   "type": "fallback",
   "time": 6,
   "job": null,
   "msg": "Carbon data was unavailable for 2 hours. The historical-average profile was used.",
   "ack": true
  }
 ],
 "bench": [
  {
   "name": "weekday mix",
   "mean": 6.5,
   "min": 1.4,
   "max": 12.9,
   "neg": 0,
   "hitBase": 100,
   "hitOpt": 100,
   "waitBase": 6,
   "waitOpt": 222
  },
  {
   "name": "tight deadlines",
   "mean": 0.7,
   "min": -0.5,
   "max": 2.2,
   "neg": 1,
   "hitBase": 100,
   "hitOpt": 98,
   "waitBase": 2,
   "waitOpt": 35
  },
  {
   "name": "api outage",
   "mean": 5.4,
   "min": -0.2,
   "max": 10.4,
   "neg": 1,
   "hitBase": 100,
   "hitOpt": 100,
   "waitBase": 5,
   "waitOpt": 226
  },
  {
   "name": "overrun cloudy",
   "mean": 2.5,
   "min": -0.8,
   "max": 6.1,
   "neg": 3,
   "hitBase": 100,
   "hitOpt": 99,
   "waitBase": 9,
   "waitOpt": 251
  },
  {
   "name": "heavy load",
   "mean": 3.8,
   "min": -1.4,
   "max": 9.5,
   "neg": 2,
   "hitBase": 97,
   "hitOpt": 95,
   "waitBase": 30,
   "waitOpt": 299
  },
  {
   "name": "uk real data",
   "mean": 23.6,
   "min": 9.8,
   "max": 45.8,
   "neg": 0,
   "hitBase": 100,
   "hitOpt": 100,
   "waitBase": 2,
   "waitOpt": 259
  }
 ]
};
