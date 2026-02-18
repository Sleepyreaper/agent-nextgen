# 🤖 Agent Monitor - Quick Reference

## ⚡ 30-Second Setup

Your monitoring system is now live and ready to use:

```
1. Start your application (python app.py)
2. Open your browser: http://localhost:5002/debug/agents
3. Upload a student application 
4. WATCH AGENTS EXECUTE IN REAL-TIME ✨
```

---

## 🎯 What You'll See

### The Dashboard

```
══════════════════════════════════════════════════════════════
 🤖 Agent Monitor - Real-Time Execution Tracker
══════════════════════════════════════════════════════════════

 Metrics:
 ┌──────────────────────────────────────────────────────────┐
 │ Total Agent Calls: 47  │ Running: 1  │ Errors: 0  │ Avg: 3.2s │
 └──────────────────────────────────────────────────────────┘

 Currently Running:
 ┌──────────────────────────────────────────────────────────┐
 │ 🤖 Naveen (School Data Scientist)         [⏳ Running]  │
 │    Model: o4miniagent                                      │
 │    Elapsed: 2.3s                                           │
 │    ▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
 └──────────────────────────────────────────────────────────┘

 Recent Executions:
 ┌──────────────────────────────────────────────────────────┐
 │ Agent                      │ Status  │ Duration │ Time     │
 ├──────────────────────────────────────────────────────────┤
 │ Naveen (School Data...)    │ ✅ done │ 4,850ms  │ 14:32:10 │
 │ Moana (School Context)     │ ✅ done │ 2,100ms  │ 14:32:05 │
 │ Tiana (Application...)     │ ✅ done │ 1,900ms  │ 14:31:59 │
 │ Rapunzel (Grade Reader)    │ ✅ done │ 980ms    │ 14:31:57 │
 └──────────────────────────────────────────────────────────┘
```

---

## 🔍 Real-Time Observations

### As Workflow Executes:

**Timeline:**
```
14:31:57 → Rapunzel starts (grades reading)
14:31:58 → Rapunzel completes (980ms)
14:31:59 → Tiana starts (application reading + school extraction)
14:32:00 → Tiana completes (1.9s)
           [School "Lincoln High School" extracted!]
14:32:01 → Naveen starts (⏳ ← THIS IS WHAT WAS INVISIBLE BEFORE!)
14:32:06 → Naveen completes (4.8s) ✅
14:32:07 → Moana starts (context analysis with enriched school data)
14:32:08 → Moana completes (1.6s)
14:32:09 → [...evaluation continues...]
```

---

## 🚀 Key Features

### ✅ Auto-Refresh
Dashboard refreshes every 2 seconds automatically
- No manual refresh needed
- See changes in real-time

### ✅ Running Agents
See animated progress bars for agents currently executing
- Shows elapsed time
- Displays model being used
- Automatic error detection

### ✅ History Tracking
Keep 10 recent executions visible
- See complete execution timeline
- Identify patterns or bottlenecks
- Check error messages

### ✅ Error Detection
Instant visibility when agents fail:
```
Agent Status: ❌ Failed
Error: "OpenAI API timed out after 30 seconds"
```

---

## 🔧 Control Buttons

On the dashboard you'll find:

**🔄 Refresh Now**
- Manually update immediately (normally auto-refreshes)
- Useful if you want immediate update

**🗑️ Clear History**
- Resets execution history (not currently running agents)
- Start fresh for clean testing

**⏹️ Auto-refresh Checkbox**
- Toggle automatic 2-second refresh
- Uncheck to pause updates

---

## 🎯 Troubleshooting with Monitor

### Issue: "Naveen not running"
1. Look for Naveen in "Currently Running" section
   - If not there: Check if Tiana successfully extracted school name
2. Look in "Recent Executions" for Naveen
   - If not listed: Moana is being skipped (school name missing)
3. Check Moana's status
   - If "⊘ Skipped": School name extraction failed in Tiana

### Issue: "Naveen running too long"
1. Check timer - how long has it been running?
   - Normal: 3-8 seconds
   - Long: 15+ seconds might indicate:
     - Complex school name requiring research
     - Azure OpenAI busy
     - Network latency
2. Check Azure Portal for OpenAI quotas
3. See detailed logs: `tail -f logs/app.log | grep -i naveen`

### Issue: "Naveen shows error"
1. Click on the error message in dashboard
2. Shows error type and details
3. Common errors:
   - `❌ School "XYZ High School" not found` → Typo in school name
   - `❌ OpenAI API timeout` → Check quota or service health
   - `❌ Database error` → PostgreSQL connection issue

---

## 📊 API Endpoints (For Advanced Users)

If you want to fetch data programmatically:

```bash
# Get current status (returns JSON)
curl http://localhost:5002/api/debug/agent-status

# Get history for specific agent (limit 50)
curl http://localhost:5002/api/debug/agent/Naveen/history?limit=50

# Clear history (POST request)
curl -X POST http://localhost:5002/api/debug/agent-status/clear
```

---

## 🎓 What Agents Report

Our system is now monitoring:
- **Naveen** (School Data Scientist) ✅ Instrumented
- **Tiana** (Application Reader) ✅ Can be instrumented
- **Rapunzel** (Grade Reader) ✅ Can be instrumented
- **Moana** (School Context) ✅ Can be instrumented
- **Merlin** (Student Evaluator) ✅ Can be instrumented
- **All others** ✅ Can be instrumented

Each shows:
- Start time, end time, total duration
- Status (running/completed/failed)
- Model used (gpt-4, o4miniagent, etc.)
- Error messages if failed

---

## 🚨 Important Notes

**The Monitor Shows:**
- ✅ Agent execution start/end times
- ✅ Agent status (running, completed, failed)
- ✅ Model being used
- ✅ Execution duration
- ✅ Error messages

**What to do if:**
- **Agent doesn't appear** → Not instrumented yet OR skipped (check Moana for "skipped" status)
- **Agent hangs** → Normal for complex operations; Naveen typically takes 3-8 seconds
- **Agent fails** → See error message for specifics; check logs with `grep -i error logs/app.log`

---

## 📝 Example Workflow

**Student uploads application for "Lincoln High School, CA"**

```
Time  Agent Name                     Status       Duration
----  -----------------------------------          --------
0s    Rapunzel (Grade Reader)        ⏳ Running
1s    Rapunzel (Grade Reader)        ✅ Completed  980ms
1s    Tiana (Application Reader)     ⏳ Running
3s    Tiana (Application Reader)     ✅ Completed  1.9s
      [Tiana extracts: school_name="Lincoln High School", state="CA"]
3s    Naveen (School Data...)        ⏳ Running
      [Checking database... NOT CACHED!]
      [Calling Naveen to analyze school...]
8s    Naveen (School Data...)        ✅ Completed  4.8s
      [School stored in cache]
8s    Moana (School Context)         ⏳ Running
      [Using Naveen's enriched data]
10s   Moana (School Context)         ✅ Completed  1.6s
10s   Merlin (Student Evaluator)    ⏳ Running
...   [... evaluation continues ...]
```

**Next student uploads for SAME school:**
```
0s    Rapunzel (Grade Reader)        ⏳ Running
1s    Rapunzel (Grade Reader)        ✅ Completed  980ms
1s    Tiana (Application Reader)     ⏳ Running
3s    Tiana (Application Reader)     ✅ Completed  1.9s
      [Tiana extracts: school_name="Lincoln High School", state="CA"]
3s    Naveen (School Data...)        ⊘ SKIPPED
      [School already in cache - Naveen NOT called!]
3s    Moana (School Context)         ⏳ Running
      [Using CACHED school data from before]
4s    Moana (School Context)         ✅ Completed  1.1s
      [Moana completes FASTER due to cached data!]
...
```

---

## 🎯 Your Next Steps

1. **Commit this code** ← You just did! ✅
2. **Deploy to your server** ← App will have monitoring built-in
3. **Run a test workflow**:
   - Upload a student application
   - Watch the dashboard fill with execution data
   - See Naveen running (finally!)
4. **If issues occur**:
   - Check `/debug/agents` dashboard
   - Use the debugging guide: `AGENT_DEBUGGING_GUIDE.md`
   - Review logs: `tail -f logs/app.log`

---

## 📞 Support

If you need more detailed monitoring:
- Check `AGENT_DEBUGGING_GUIDE.md` for detailed troubleshooting
- Review `TELEMETRY_IMPLEMENTATION_GUIDE.md` for adding monitoring to more agents
- See `src/agents/agent_monitor.py` for the implementation

Your visibility into agent execution is now complete! 🎉
