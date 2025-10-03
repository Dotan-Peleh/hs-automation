import React, { useState, useMemo, useEffect } from 'react';
import { LineChart, Line, BarChart, Bar, PieChart, Pie, Cell, AreaChart, Area, RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { Calendar, TrendingUp, AlertTriangle, Bug, Zap, Monitor, Mail, Filter, Activity, AlertCircle, CheckCircle, Clock } from 'lucide-react';
// Trigger new build
const generateMockData = () => {
  const categories = ['Bug', 'Crash', 'UX Issue', 'Performance', 'Technical', 'Question', 'Feature Request'];
  const platforms = ['PC', 'PlayStation', 'Xbox', 'Mobile', 'Switch'];
  const severities = ['Critical', 'High', 'Medium', 'Low'];
  
  // Generate 30 days of data
  const dailyData: any[] = [];
  const today = new Date();
  for (let i = 29; i >= 0; i--) {
    const date = new Date(today);
    date.setDate(date.getDate() - i);
    dailyData.push({
      date: date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      bugs: Math.floor(Math.random() * 20) + 5,
      crashes: Math.floor(Math.random() * 15) + 3,
      uxIssues: Math.floor(Math.random() * 12) + 2,
      performance: Math.floor(Math.random() * 10) + 2,
      technical: Math.floor(Math.random() * 8) + 1,
      questions: Math.floor(Math.random() * 25) + 10,
      features: Math.floor(Math.random() * 6) + 1,
      total: 0
    });
    dailyData[dailyData.length - 1].total = 
      dailyData[dailyData.length - 1].bugs +
      dailyData[dailyData.length - 1].crashes +
      dailyData[dailyData.length - 1].uxIssues +
      dailyData[dailyData.length - 1].performance +
      dailyData[dailyData.length - 1].technical +
      dailyData[dailyData.length - 1].questions +
      dailyData[dailyData.length - 1].features;
  }
  
  // Category distribution
  const categoryData = categories.map(cat => ({
    name: cat,
    value: Math.floor(Math.random() * 100) + 20,
    percentage: 0 as any
  }));
  const totalCat = categoryData.reduce((acc, curr) => acc + curr.value, 0);
  categoryData.forEach(cat => (cat.percentage = (((cat.value / totalCat) * 100)).toFixed(1) as any));
  
  // Platform distribution
  const platformData = platforms.map(platform => ({
    platform,
    issues: Math.floor(Math.random() * 80) + 20
  }));
  
  // Severity distribution
  const severityData = severities.map(severity => ({
    severity,
    count: Math.floor(Math.random() * 50) + 10,
    resolved: Math.floor(Math.random() * 40) + 5
  }));
  
  // Response time metrics
  const responseTimeData = [
    { hour: '0-1h', count: 45 },
    { hour: '1-3h', count: 78 },
    { hour: '3-6h', count: 123 },
    { hour: '6-12h', count: 89 },
    { hour: '12-24h', count: 56 },
    { hour: '24h+', count: 34 }
  ];
  
  // Top issues
  const topIssues = [
    { id: 1, title: 'Game crashes on level 5 boss fight', category: 'Crash', count: 234, trend: 'up', severity: 'Critical' },
    { id: 2, title: 'Unable to save progress after update', category: 'Bug', count: 189, trend: 'up', severity: 'Critical' },
    { id: 3, title: 'Inventory UI overlapping on mobile', category: 'UX Issue', count: 156, trend: 'down', severity: 'High' },
    { id: 4, title: 'Frame drops in multiplayer mode', category: 'Performance', count: 134, trend: 'stable', severity: 'High' },
    { id: 5, title: 'Audio cutting out randomly', category: 'Technical', count: 98, trend: 'down', severity: 'Medium' }
  ];
  
  // Radar chart data for issue patterns
  const radarData = [
    { aspect: 'Gameplay', current: 85, previous: 72 },
    { aspect: 'Graphics', current: 65, previous: 58 },
    { aspect: 'Audio', current: 45, previous: 62 },
    { aspect: 'Network', current: 78, previous: 81 },
    { aspect: 'Controls', current: 52, previous: 48 },
    { aspect: 'UI/UX', current: 69, previous: 55 }
  ];
  
  return {
    dailyData,
    categoryData,
    platformData,
    severityData,
    responseTimeData,
    topIssues,
    radarData
  };
};

const Dashboard = () => {
  const [selectedTimeRange, setSelectedTimeRange] = useState('30d');
  const [selectedCategory, setSelectedCategory] = useState('all');
  // Stable, non-random initial state to avoid SSR/client mismatch
  const getEmptyData = () => {
    const today = new Date();
    const dailyData = Array.from({ length: 30 }).map((_, i) => {
      const d = new Date(today);
      d.setDate(d.getDate() - (29 - i));
      return { date: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }), bugs: 0, crashes: 0, uxIssues: 0, performance: 0, technical: 0, questions: 0, features: 0, total: 0 };
    });
    return {
      dailyData,
      categoryData: [
        { name: 'Bug', value: 0, percentage: '0.0' },
        { name: 'Crash', value: 0, percentage: '0.0' },
        { name: 'UX Issue', value: 0, percentage: '0.0' },
        { name: 'Performance', value: 0, percentage: '0.0' },
        { name: 'Technical', value: 0, percentage: '0.0' },
        { name: 'Question', value: 0, percentage: '0.0' },
        { name: 'Feature Request', value: 0, percentage: '0.0' },
      ],
      platformData: [],
      severityData: [
        { severity: 'Critical', count: 0, resolved: 0 },
        { severity: 'High', count: 0, resolved: 0 },
        { severity: 'Medium', count: 0, resolved: 0 },
        { severity: 'Low', count: 0, resolved: 0 },
      ],
      responseTimeData: [],
      topIssues: [],
      priorityIssue: null,
      priorityIssues: [],
      radarData: [],
    } as any;
  };
  const [data, setData] = useState(getEmptyData());
  // Insights state
  const [insightsCats, setInsightsCats] = useState<any[]>([]);
  const [insightsWords, setInsightsWords] = useState<any[]>([]);
  const [issueAnalysis, setIssueAnalysis] = useState<any | null>(null);
  const [insightRecs, setInsightRecs] = useState<any[]>([]);
  const [toastMsg, setToastMsg] = useState<string>('');
  const [dismissedIds, setDismissedIds] = useState<Set<number>>(new Set());
  const [feedbackTicket, setFeedbackTicket] = useState<any>(null);
  const [globalSummary, setGlobalSummary] = useState('');

  // Remove mock injection; rely on live data only

  // Fetch dismissed tickets
  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8080';
    fetch(base + '/admin/ticket/dismissed')
      .then(res => res.json())
      .then(data => {
        setDismissedIds(new Set(data.dismissed || []));
      })
      .catch(() => {});
  }, []);

  // Submit tag correction feedback
  const submitFeedback = async (convId: number, correctIntent: string, correctSeverity: string, notes: string) => {
    const base = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8080';
    try {
      await fetch(base + '/admin/ticket/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conv_id: convId,
          correct_intent: correctIntent,
          correct_severity: correctSeverity,
          notes: notes
        })
      });
      setToastMsg('🧠 Feedback saved! Model will learn from this.');
      setTimeout(() => setToastMsg(''), 4000);
      setFeedbackTicket(null);
    } catch (e) {
      console.error('Failed to submit feedback:', e);
      setToastMsg('❌ Failed to save feedback');
      setTimeout(() => setToastMsg(''), 3000);
    }
  };

  // Mark ticket as done/seen (toggle)
  const markAsSeen = async (convId: number) => {
    const base = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8080';
    const isDismissed = dismissedIds.has(convId);
    
    try {
      if (isDismissed) {
        // Unmark - remove from dismissed set
        await fetch(base + '/admin/ticket/unmark', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ conv_id: convId })
        });
        const newSet = new Set(Array.from(dismissedIds));
        newSet.delete(convId);
        setDismissedIds(newSet);
        setToastMsg('↩️ Ticket unmarked');
        setTimeout(() => setToastMsg(''), 2000);
      } else {
        // Mark as done
        await fetch(base + '/admin/ticket/mark_seen', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ conv_id: convId, action: 'dismissed' })
        });
        setDismissedIds(prev => new Set(Array.from(prev).concat(convId)));
        setToastMsg('✅ Ticket marked as done');
        setTimeout(() => setToastMsg(''), 3000);
      }
    } catch (e) {
      console.error('Failed to mark as seen:', e);
    }
  };

  // Fetch live backend stats for last 48h to reflect real HS data
  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8080';
    (async () => {
      try {
        // Trigger a quick delta backfill on each dashboard load
        try { await fetch(base + '/admin/backfill?limit_pages=1'); } catch {}
        const res = await fetch(base + '/admin/dashboard?hours=168');
        if (res.ok) {
          const j = await res.json();
          setData((prev) => ({
            ...prev,
            dailyData: j.dailyData?.length ? j.dailyData : prev.dailyData,
            categoryData: j.categoryData?.length ? j.categoryData : prev.categoryData,
            platformData: j.platformData || prev.platformData,
            severityData: j.severityData || prev.severityData,
            topIssues: j.topIssues || prev.topIssues,
            priorityIssue: j.priorityIssue || null,
            priorityIssues: j.priorityIssues || prev.priorityIssues || [],
          }));
        }
      } catch (_) {
        // keep mock data if backend not available
      }
    })();
  }, []);

  // Fetch LLM-powered Insights (summaries, tags, patterns) with loading and incremental paging
  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8080';
    let cancelled = false;
    let latestNumber: number = 0;
    (async () => {
      try {
        // Ensure we have most recent tickets before analyzing
        try { await fetch(base + '/admin/backfill?limit_pages=1'); } catch {}
        setInsightRecs([{ __loading: true, __progress: 'Fetching page 1…' } as any]);
        const pageSize = 20; // Reduced from 50 for faster initial load
        let page = 1;
        let aggregated: any[] = [];
        while (!cancelled) {
          const url = `${base}/admin/insights?hours=48&limit=${pageSize}&page=${page}${latestNumber?`&min_number=${latestNumber}`:''}`;
          if (!cancelled) setInsightRecs((cur)=>[{ __loading: true, __progress: `Fetching page ${page}…` } as any, ...cur.filter((x:any)=>!x.__loading)]);
          const res = await fetch(url);
          if (!res.ok) break;
          const j = await res.json();
          if (page === 1) {
            setInsightsCats(j.top_categories || []);
            setInsightsWords(j.top_keywords || []);
            // Merge reply counts into issue_analysis
            const analysis = j.issue_analysis || {};
            analysis.replied_count = j.replied_count || 0;
            analysis.unreplied_count = j.unreplied_count || 0;
            setIssueAnalysis(analysis);
            if (j.global_summary) {
              setGlobalSummary(j.global_summary);
            }
          }
          const batch: any[] = j.recommendations || [];
          if (!batch.length) break;
          const seen = new Set(aggregated.map(x=>x.id));
          for (const r of batch) {
            if (!seen.has(r.id)) aggregated.push(r);
            if (typeof r.number === 'number') latestNumber = Math.max(latestNumber, r.number);
          }
          const clusterCounts: Record<string, number> = {};
          for (const r of aggregated) {
            if (r.cluster_key) clusterCounts[r.cluster_key] = (clusterCounts[r.cluster_key] || 0) + 1;
          }
          const recsOut = aggregated
            .map((r: any) => ({ ...r, similar_count: r.cluster_key ? clusterCounts[r.cluster_key] : 1 }))
            .sort((a:any,b:any)=> (b.number||0)-(a.number||0));
          if (!cancelled) setInsightRecs(recsOut);
          const expectedTotal = Number(j.total || 0);
          if (expectedTotal && aggregated.length >= expectedTotal) break;
          page += 1;
          await new Promise(r=>setTimeout(r, 50)); // Reduced from 150ms for faster paging
        }
      } catch (_) { /* no-op */ }
    })();
    return () => { cancelled = true; };
  }, []);
  
  // Real-time: subscribe to server-sent events and refresh newest items
  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8080';
    let es: EventSource | null = null;
    try {
      es = new EventSource(base + '/admin/events');
      es.onmessage = async (ev) => {
        try {
          const e = JSON.parse(ev.data || '{}');
          if (e && e.type === 'new_message') {
            setToastMsg(`🔔 NEW MESSAGE #${e.number || e.conv_id}: ${e.subject || 'No subject'}`);
            setTimeout(() => setToastMsg(''), 8000);
            // fetch the freshest page and merge (dedupe by id)
            try {
              const res = await fetch(`${base}/admin/insights?hours=12&limit=20&page=1`);
              if (res.ok) {
                const j = await res.json();
                const batch: any[] = j.recommendations || [];
                setInsightRecs((cur) => {
                  const seen = new Set((cur || []).map((x: any) => x.id));
                  const newOnes = batch.filter((x: any) => !seen.has(x.id)).map((x: any) => ({ ...x, __new: true }));
                  const merged = [...newOnes, ...(cur || [])];
                  // Scroll to top to show new message
                  if (newOnes.length > 0) {
                    setTimeout(() => window.scrollTo({ top: 0, behavior: 'smooth' }), 100);
                  }
                  return merged.slice(0, 200);
                });
                // auto-clear the "New" badge after 10 seconds
                setTimeout(() => {
                  setInsightRecs((cur) => (cur || []).map((x: any) => ({ ...x, __new: false })));
                }, 10000);
              }
            } catch {}
          }
        } catch {}
      };
    } catch {}
    return () => { try { es && es.close(); } catch {} };
  }, []);

  // Calculate summary stats
  const summaryStats = useMemo(() => {
    const total = data.dailyData.reduce((acc: number, curr: any) => acc + (curr.total || 0), 0);
    const avgPerDay = data.dailyData.length ? (total / data.dailyData.length).toFixed(1) : '0.0';
    const todayTotal = data.dailyData[data.dailyData.length - 1]?.total || 0;
    const yesterdayTotal = data.dailyData[data.dailyData.length - 2]?.total || 0;
    const change = yesterdayTotal ? (((todayTotal - yesterdayTotal) / yesterdayTotal) * 100).toFixed(1) : '0.0';
    
    return {
      total,
      avgPerDay,
      todayTotal,
      change,
      resolved: Math.floor(total * 0.68),
      pending: Math.floor(total * 0.32),
      avgResponseTime: '3.2h'
    };
  }, [data]);
  
  // Colors for charts
  const COLORS = ['#8b5cf6', '#ef4444', '#f59e0b', '#10b981', '#3b82f6', '#ec4899', '#6366f1'];
  const categoryColors: Record<string, string> = {
    'Bug': '#ef4444',
    'Crash': '#dc2626',
    'UX Issue': '#f59e0b',
    'Performance': '#8b5cf6',
    'Technical': '#3b82f6',
    'Question': '#10b981',
    'Feature Request': '#6366f1'
  };
  
  const severityColors: Record<string, string> = {
    'Critical': '#dc2626',
    'High': '#f59e0b',
    'Medium': '#3b82f6',
    'Low': '#10b981'
  };
  
  // Build a concise fallback description when LLM summary is absent
  const getShortDescription = (r: any): string => {
    try {
      const cap = (s: string) => (s && typeof s === 'string') ? (s.charAt(0).toUpperCase() + s.slice(1)) : '';
      const sev = String(r?.severity_bucket || 'medium').toLowerCase();
      const categories = Array.isArray(r?.categories) ? r.categories : [];
      const primaryCat = (categories[0] ? String(categories[0]).replace(/_/g, ' ') : 'support request');
      const intentRaw: string | undefined = (Array.isArray(r?.suggested_tags) ? r.suggested_tags.find((t: string)=>/^intent:/i.test(t)) : undefined);
      const intent = intentRaw ? String(intentRaw.split(':',2)[1] || '').toLowerCase() : '';
      const intentMap: Record<string,string> = {
        'refund_request': 'refund request',
        'cancel_subscription': 'subscription cancellation',
        'account_access': 'account access issue',
        'account_deletion': 'account deletion request',
        'recover_progress': 'recover lost progress',
        'bug_report': 'bug/crash report',
        'performance_issue': 'performance issue',
        'feature_request': 'feature request',
        'how_to': 'how‑to question',
        'device_migration': 'device migration/restore',
      };
      const platform = r?.entities?.platform ? String(r.entities.platform) : '';
      const appv = r?.entities?.app_version ? `v${r.entities.app_version}` : '';
      const lvl = (typeof r?.entities?.level === 'number') ? `lvl ${r.entities.level}` : '';
      const similar = (typeof r?.similar_count === 'number' && r.similar_count > 1) ? `${r.similar_count} similar` : '';
      const parts = [
        `${sev} ${intent ? intentMap[intent] || intent : primaryCat}`.trim(),
        platform ? `on ${platform}` : '',
        appv,
        lvl,
      ].filter(Boolean);
      const main = parts.join(' ');
      return similar ? `${cap(main)} — ${similar}` : cap(main);
    } catch {
      return 'Support request';
    }
  };
  
  return (
    <div className="min-h-screen bg-gray-50 p-6">
      {toastMsg && (
        <div className="fixed top-4 right-4 bg-gradient-to-r from-purple-600 to-pink-600 text-white px-6 py-3 rounded-lg shadow-2xl z-50 animate-pulse border-2 border-white">
          <div className="text-sm font-bold">{toastMsg}</div>
        </div>
      )}
      
      {/* Feedback Modal */}
      {feedbackTicket && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-2xl max-w-lg w-full p-6">
            <h3 className="text-lg font-bold text-gray-900 mb-4">🏷️ Fix Tags for #{feedbackTicket.number}</h3>
            <div className="text-sm text-gray-700 mb-4">{feedbackTicket.subject}</div>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Correct Intent</label>
                <select id="intent-select" className="w-full px-3 py-2 border border-gray-300 rounded-lg">
                  <option value="">Keep current</option>
                  <option value="bug_report">🐛 Bug/Crash Report</option>
                  <option value="how_to">❓ How-To Question</option>
                  <option value="refund_request">💰 Refund Request</option>
                  <option value="cancel_subscription">🚫 Cancel Subscription</option>
                  <option value="recover_progress">💾 Lost Progress</option>
                  <option value="account_access">🔐 Account Access</option>
                  <option value="monetization_complaint">💸 Monetization Feedback</option>
                  <option value="gameplay_feedback">🎮 Gameplay Feedback</option>
                  <option value="beta_feedback">💭 Beta Feedback</option>
                </select>
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Correct Severity</label>
                <select id="severity-select" className="w-full px-3 py-2 border border-gray-300 rounded-lg">
                  <option value="">Keep current</option>
                  <option value="critical">🔴 Critical</option>
                  <option value="high">🟠 High</option>
                  <option value="medium">🔵 Medium</option>
                  <option value="low">🟢 Low</option>
                </select>
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Notes (optional)</label>
                <textarea
                  id="notes-input"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                  rows={3}
                  placeholder="Why was this wrong? Help the AI learn..."
                />
              </div>
              
              <div className="flex gap-3">
                <button
                  onClick={() => {
                    const intent = (document.getElementById('intent-select') as HTMLSelectElement).value;
                    const severity = (document.getElementById('severity-select') as HTMLSelectElement).value;
                    const notes = (document.getElementById('notes-input') as HTMLTextAreaElement).value;
                    submitFeedback(feedbackTicket.id, intent, severity, notes);
                  }}
                  className="flex-1 px-4 py-2 bg-blue-600 text-white font-semibold rounded-lg hover:bg-blue-700 transition-colors"
                >
                  Submit Feedback
                </button>
                <button
                  onClick={() => setFeedbackTicket(null)}
                  className="px-4 py-2 bg-gray-200 text-gray-700 font-semibold rounded-lg hover:bg-gray-300 transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">🎮 Game Support Dashboard</h1>
        <p className="text-gray-600">Monitor and analyze user feedback trends from support emails</p>
      </div>

      {/* Global Summary */}
      {globalSummary && (
        <div className="mb-6 bg-yellow-50 border-l-4 border-yellow-400 p-4 rounded-r-lg">
          <h3 className="text-sm font-bold text-yellow-800 mb-1">💡 AI Summary</h3>
          <p className="text-sm text-yellow-900">{globalSummary}</p>
        </div>
      )}
      
      {/* Filters Bar */}
      {/* Filters/Export bar removed per request */}
      
      {/* Summary Cards removed per request */}
      
      {/* PRIORITY ISSUES FIRST - What needs attention NOW */}
      <div className="mb-6 bg-white rounded-lg shadow-sm p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <AlertCircle className="w-5 h-5 text-red-600" />
          🚨 Priority Tickets (Critical & High)
        </h3>
          {insightRecs.filter((r:any)=> !r.__loading && r.severity_bucket && ['critical','high'].includes(r.severity_bucket.toLowerCase()) && !dismissedIds.has(r.id)).length > 0 ? (
            <div className="space-y-3">
              {insightRecs
                .filter((r:any)=> !r.__loading && r.severity_bucket && ['critical','high'].includes(r.severity_bucket.toLowerCase()) && !dismissedIds.has(r.id))
                .slice(0, 5)
                .map((r:any)=> {
                const intentTag = (r.suggested_tags || []).find((t: string) => t.startsWith('intent:'));
                const intent = intentTag ? intentTag.split(':')[1] : '';
                
                const getIntentColor = () => {
                  if (intent.includes('beta') || intent === 'beta_feedback') return 'bg-gray-50 border-gray-200';
                  if (intent.includes('bug') || intent.includes('crash')) return 'bg-red-100 border-red-300';
                  if (intent.includes('how_to')) return 'bg-blue-100 border-blue-300';
                  if (intent.includes('refund') || intent.includes('cancel')) return 'bg-yellow-100 border-yellow-300';
                  if (intent.includes('progress') || intent.includes('recover')) return 'bg-purple-100 border-purple-300';
                  if (intent.includes('account')) return 'bg-orange-100 border-orange-300';
                  if (intent.includes('monetization') || intent.includes('complaint')) return 'bg-pink-50 border-pink-200';
                  if (intent.includes('gameplay') && !intent.includes('beta')) return 'bg-emerald-50 border-emerald-200';
                  return 'bg-gray-100 border-gray-300';
                };
                
                const getIntentLabel = () => {
                  if (intent.includes('beta') || intent === 'beta_feedback') return '💭 Beta Feedback';
                  if (intent.includes('bug') || intent.includes('crash')) return '🐛 Bug/Crash';
                  if (intent.includes('how_to')) return '❓ How-To';
                  if (intent.includes('refund')) return '💰 Refund';
                  if (intent.includes('cancel')) return '🚫 Cancel Sub';
                  if (intent.includes('progress')) return '💾 Lost Progress';
                  if (intent.includes('account')) return '🔐 Account';
                  if (intent.includes('monetization') || intent.includes('complaint')) return '💸 Monetization';
                  if (intent.includes('gameplay') && !intent.includes('beta')) return '🎮 Gameplay';
                  return '📋 Support';
                };

                return (
                  <div key={r.id} className={`border-2 rounded-lg p-4 ${getIntentColor()}`}>
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-2 flex-wrap">
                          <span className={`px-2 py-1 rounded-full text-xs font-semibold text-white ${
                            r.severity_bucket === 'critical' ? 'bg-red-600' : 'bg-orange-500'
                          }`}>
                            {r.severity_bucket.toUpperCase()}
                          </span>
                          <span className="px-2 py-1 rounded-full text-xs font-semibold bg-white border border-gray-300">
                            {getIntentLabel()}
                          </span>
                          <span className="text-xs font-semibold text-gray-700">#{r.number}</span>
                          {r.similar_count > 1 && (
                            <span className="px-2 py-1 rounded-full text-xs bg-white border border-gray-400 font-semibold">
                              {r.similar_count} similar
                            </span>
                          )}
                        </div>
                        <div className="text-sm font-semibold text-gray-900 mb-1">{r.subject || 'No subject'}</div>
                        {r.one_liner && (
                          <div className="text-xs text-gray-700 mb-1">{r.one_liner}</div>
                        )}
                        {r.escalation_reason && (
                          <div className="text-xs font-semibold text-red-700 mb-2 px-2 py-1 bg-red-50 rounded border border-red-200 inline-block">
                            {r.escalation_reason}
                          </div>
                        )}
                        {/* Show tags in priority section */}
                        <div className="flex flex-wrap gap-1 mb-2">
                          {(r.suggested_tags || [])
                            .filter((t: string) => !t.startsWith('sev:') && !t.startsWith('intent:'))
                            .slice(0, 6)
                            .map((t: string) => {
                              const lower = t.toLowerCase();
                              let color = 'bg-gray-100 text-gray-700';
                              let label = t;
                              
                              if (lower.includes('crash')) {
                                color = 'bg-red-100 text-red-800 border border-red-300 font-semibold';
                                label = '🔥 Crash';
                              } else if (lower.includes('freeze')) {
                                color = 'bg-cyan-100 text-cyan-800 border border-cyan-300 font-semibold';
                                label = '❄️ Freeze';
                              } else if (lower.includes('item') && lower.includes('stuck')) {
                                color = 'bg-rose-100 text-rose-800 border border-rose-300 font-semibold';
                                label = '🎯 Item Stuck';
                              } else if (lower.includes('progress') || lower.includes('lost')) {
                                color = 'bg-purple-100 text-purple-800 border border-purple-300 font-semibold';
                                label = '💾 Progress Lost';
                              } else if (lower.includes('how_to') || lower.includes('how to')) {
                                color = 'bg-blue-100 text-blue-800 border border-blue-300 font-semibold';
                                label = '❓ How-To';
                              }
                              
                              return (
                                <span key={t} className={`px-2 py-0.5 rounded-full text-xs ${color}`}>
                                  {label}
                                </span>
                              );
                            })}
                        </div>
                        <div className="flex items-center gap-3 text-xs text-gray-600 flex-wrap">
                          {r.customer_name && <span>👤 {r.customer_name}</span>}
                          {r.distinct_id && (
                            <span className="px-2 py-0.5 rounded bg-gray-100 font-mono text-gray-800">
                              ID: {r.distinct_id}
                            </span>
                          )}
                          {r.entities?.platform && <span>📱 {r.entities.platform}</span>}
                          {r.entities?.app_version && <span>🔢 v{r.entities.app_version}</span>}
                          {r.updated_at && <span>🕐 {new Date(r.updated_at).toLocaleString()}</span>}
                        </div>
                      </div>
                      <div className="flex-shrink-0 flex flex-col gap-2">
                        {r.hs_link && (
                          <a
                            href={r.hs_link}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 px-3 py-2 bg-purple-600 text-white text-xs font-semibold rounded-lg hover:bg-purple-700 transition-colors"
                          >
                            Open in HS →
                          </a>
                        )}
                        <button
                          onClick={() => markAsSeen(r.id)}
                          className="inline-flex items-center justify-center gap-1 px-3 py-2 bg-green-100 text-green-700 text-xs font-semibold rounded-lg hover:bg-green-200 transition-colors border border-green-300"
                        >
                          ✓ Mark as Done
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
          </div>
        ) : (
          <div className="text-sm text-gray-500">✅ No critical or high priority tickets right now</div>
        )}
      </div>

      {/* CHARTS - Visual Overview */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        {/* Trend Chart - Takes 2/3 of width */}
        <div className="bg-white rounded-lg shadow-sm p-6 lg:col-span-2">
          <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-purple-600" />
            Issue Trends Over Time
          </h3>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={data.dailyData}>
              <defs>
                <linearGradient id="colorBugs" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#f97316" stopOpacity={0.8}/>
                  <stop offset="95%" stopColor="#f97316" stopOpacity={0}/>
                </linearGradient>
                <linearGradient id="colorCrashes" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#dc2626" stopOpacity={0.8}/>
                  <stop offset="95%" stopColor="#dc2626" stopOpacity={0}/>
                </linearGradient>
                <linearGradient id="colorUX" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#eab308" stopOpacity={0.8}/>
                  <stop offset="95%" stopColor="#eab308" stopOpacity={0}/>
                </linearGradient>
                <linearGradient id="colorPayments" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.8}/>
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                </linearGradient>
                <linearGradient id="colorPerformance" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.8}/>
                  <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0}/>
                </linearGradient>
                <linearGradient id="colorQuestions" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#10b981" stopOpacity={0.8}/>
                  <stop offset="95%" stopColor="#10b981" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="ts" tick={{ fontSize: 12 }} stroke="#6b7280" tickFormatter={(v:any)=>{
                try { return new Date(v).toLocaleTimeString([], { hour: 'numeric' }); } catch { return v; }
              }} />
              <YAxis tick={{ fontSize: 12 }} stroke="#6b7280" allowDecimals={false} />
              <Tooltip 
                content={({ active, payload }) => {
                  if (!active || !payload || !payload.length) return null;
                  const data = payload[0].payload;
                  return (
                    <div className="bg-white border border-gray-200 rounded-lg shadow-lg p-3">
                      <div className="text-xs font-semibold text-gray-700 mb-2">
                        {new Date(data.ts).toLocaleString()}
                      </div>
                      <div className="space-y-1 text-xs">
                        <div className="flex items-center justify-between gap-3">
                          <span className="flex items-center gap-1">
                            <span className="w-2 h-2 rounded-full" style={{backgroundColor: '#f97316'}}></span>
                            Bugs
                          </span>
                          <span className="font-semibold">{data.bugs || 0}</span>
                        </div>
                        <div className="flex items-center justify-between gap-3">
                          <span className="flex items-center gap-1">
                            <span className="w-2 h-2 rounded-full" style={{backgroundColor: '#dc2626'}}></span>
                            Crashes
                          </span>
                          <span className="font-semibold">{data.crashes || 0}</span>
                        </div>
                        <div className="flex items-center justify-between gap-3">
                          <span className="flex items-center gap-1">
                            <span className="w-2 h-2 rounded-full" style={{backgroundColor: '#eab308'}}></span>
                            UX Issues
                          </span>
                          <span className="font-semibold">{data.uxIssues || 0}</span>
                        </div>
                        <div className="flex items-center justify-between gap-3">
                          <span className="flex items-center gap-1">
                            <span className="w-2 h-2 rounded-full" style={{backgroundColor: '#3b82f6'}}></span>
                            Payments
                          </span>
                          <span className="font-semibold">{data.payments || 0}</span>
                        </div>
                        <div className="flex items-center justify-between gap-3">
                          <span className="flex items-center gap-1">
                            <span className="w-2 h-2 rounded-full" style={{backgroundColor: '#8b5cf6'}}></span>
                            Performance
                          </span>
                          <span className="font-semibold">{data.performance || 0}</span>
                        </div>
                        <div className="flex items-center justify-between gap-3">
                          <span className="flex items-center gap-1">
                            <span className="w-2 h-2 rounded-full" style={{backgroundColor: '#10b981'}}></span>
                            Questions
                          </span>
                          <span className="font-semibold">{data.questions || 0}</span>
                        </div>
                        <div className="border-t border-gray-200 mt-2 pt-2 flex items-center justify-between gap-3">
                          <span className="font-bold">Total</span>
                          <span className="font-bold">{data.total || 0}</span>
                        </div>
                      </div>
                    </div>
                  );
                }}
              />
              <Area type="monotone" dataKey="bugs" name="Bugs" stackId="1" stroke="#f97316" strokeWidth={2} fillOpacity={1} fill="url(#colorBugs)" />
              <Area type="monotone" dataKey="crashes" name="Crashes" stackId="1" stroke="#dc2626" strokeWidth={2} fillOpacity={1} fill="url(#colorCrashes)" />
              <Area type="monotone" dataKey="uxIssues" name="UX Issues" stackId="1" stroke="#eab308" strokeWidth={2} fillOpacity={1} fill="url(#colorUX)" />
              <Area type="monotone" dataKey="payments" name="Payments" stackId="1" stroke="#3b82f6" strokeWidth={2} fillOpacity={1} fill="url(#colorPayments)" />
              <Area type="monotone" dataKey="performance" name="Performance" stackId="1" stroke="#8b5cf6" strokeWidth={2} fillOpacity={1} fill="url(#colorPerformance)" />
              <Area type="monotone" dataKey="questions" name="Questions" stackId="1" stroke="#10b981" strokeWidth={2} fillOpacity={1} fill="url(#colorQuestions)" />
              <Legend />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        
        {/* Quick Insights Summary - Takes 1/3 of width */}
        <div className="bg-white rounded-lg shadow-sm p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">📊 24h Summary</h3>
          <div className="space-y-4">
            {/* Response Status */}
            {issueAnalysis && (
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
                <div className="text-xs font-medium text-gray-700 mb-1">Response Status</div>
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-2xl font-bold text-blue-600">
                      {issueAnalysis.replied_count || 0}/{(issueAnalysis.replied_count || 0) + (issueAnalysis.unreplied_count || 0)}
                    </div>
                    <div className="text-xs text-gray-600">Replied</div>
                  </div>
                  {issueAnalysis.unreplied_count > 0 && (
                    <div className="text-right">
                      <div className="text-lg font-bold text-orange-600">
                        {issueAnalysis.unreplied_count}
                      </div>
                      <div className="text-xs text-gray-600">Need Response</div>
                    </div>
                  )}
                </div>
              </div>
            )}
            <div>
              <div className="text-xs font-medium text-gray-700 mb-2">Top Intents</div>
              <div className="space-y-1">
                {(issueAnalysis?.intents || []).slice(0,5).map((i:any)=> (
                  <div key={i.name} className="flex items-center justify-between text-xs">
                    <span className="capitalize text-gray-700">{String(i.name).replace(/_/g,' ')}</span>
                    <span className="font-semibold text-gray-900">{i.count}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="border-t pt-3">
              <div className="text-xs font-medium text-gray-700 mb-2">Platforms</div>
              <div className="space-y-1">
                {(issueAnalysis?.platforms || []).slice(0,5).map((p:any)=> (
                  <div key={p.name} className="flex items-center justify-between text-xs">
                    <span className="capitalize text-gray-700">{p.name}</span>
                    <span className="font-semibold text-gray-900">{p.count}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="border-t pt-3">
              <div className="text-xs font-medium text-gray-700 mb-2">Severity</div>
              <div className="space-y-1">
                {(issueAnalysis?.severities || []).map((s:any)=> (
                  <div key={s.bucket} className="flex items-center justify-between text-xs">
                    <span className={`font-semibold ${
                      s.bucket === 'Critical' ? 'text-red-600' :
                      s.bucket === 'High' ? 'text-orange-600' :
                      s.bucket === 'Medium' ? 'text-blue-600' : 'text-green-600'
                    }`}>{s.bucket}</span>
                    <span className="font-bold text-gray-900">{s.count}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
      
      {/* Secondary Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* Platform Distribution */}
        <div className="bg-white rounded-lg shadow-sm p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <Monitor className="w-5 h-5 text-purple-600" />
            Platform Distribution
          </h3>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={data.platformData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="platform" tick={{ fontSize: 12 }} stroke="#6b7280" />
              <YAxis tick={{ fontSize: 12 }} stroke="#6b7280" />
              <Tooltip />
              <Bar dataKey="issues" fill="#8b5cf6" radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        
        {/* Severity Distribution */}
        <div className="bg-white rounded-lg shadow-sm p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <AlertTriangle className="w-5 h-5 text-purple-600" />
            Severity Levels
          </h3>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={data.severityData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="severity" tick={{ fontSize: 12 }} stroke="#6b7280" />
              <YAxis tick={{ fontSize: 12 }} stroke="#6b7280" />
              <Tooltip />
              <Bar dataKey="count" fill="#ef4444" radius={[8, 8, 0, 0]}>
                {data.severityData.map((entry: any, index: number) => (
                  <Cell key={`cell-${index}`} fill={severityColors[entry.severity]} />
                ))}
              </Bar>
              <Bar dataKey="resolved" fill="#10b981" radius={[8, 8, 0, 0]} />
              <Legend />
            </BarChart>
          </ResponsiveContainer>
        </div>
        
        {/* Response Time Distribution removed per request */}
      </div>
      
      {/* ALL MESSAGES - Detailed List at Bottom */}
      <div className="mt-6 bg-white rounded-lg shadow-sm p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">📋 All Recent Messages (48h)</h3>
            <div className="space-y-3">
          {(insightRecs.filter((x:any)=>!x.__loading).length === 0) && (
              <div className="space-y-3">
              {[1, 2, 3, 4, 5].map(i => (
                <div key={i} className="border rounded-lg p-3 bg-gray-50 animate-pulse">
                  <div className="flex items-center gap-2 mb-2">
                    <div className="h-5 w-16 bg-gray-300 rounded-full"></div>
                    <div className="h-5 w-24 bg-gray-300 rounded-full"></div>
                    <div className="h-5 w-12 bg-gray-300 rounded-full"></div>
                  </div>
                  <div className="h-4 bg-gray-300 rounded w-3/4 mb-2"></div>
                  <div className="h-3 bg-gray-200 rounded w-1/2"></div>
              </div>
            ))}
            </div>
          )}
          {insightRecs
            .filter((x:any)=>!x.__loading)
            .sort((a:any,b:any)=> (b.number||0)-(a.number||0))
            .map((r: any) => {
              const intentTag = (r.suggested_tags || []).find((t: string) => t.startsWith('intent:'));
              const intent = intentTag ? intentTag.split(':')[1] : '';
              
              const getIntentColor = () => {
                if (intent.includes('beta') || intent === 'beta_feedback') return 'bg-gray-50 border-gray-200';
                if (intent.includes('bug') || intent.includes('crash')) return 'bg-red-50 border-red-200';
                if (intent.includes('how_to')) return 'bg-blue-50 border-blue-200';
                if (intent.includes('refund') || intent.includes('cancel')) return 'bg-yellow-50 border-yellow-200';
                if (intent.includes('progress') || intent.includes('recover')) return 'bg-purple-50 border-purple-200';
                if (intent.includes('account')) return 'bg-orange-50 border-orange-200';
                if (intent.includes('monetization') || intent.includes('complaint')) return 'bg-pink-50 border-pink-200';
                if (intent.includes('gameplay') && !intent.includes('beta')) return 'bg-emerald-50 border-emerald-200';
                return 'bg-white border-gray-200';
              };
              
              const getIntentLabel = () => {
                if (intent.includes('beta') || intent === 'beta_feedback') return '💭 Beta Feedback';
                if (intent.includes('bug') || intent.includes('crash')) return '🐛 Bug/Crash';
                if (intent.includes('how_to')) return '❓ How-To';
                if (intent.includes('refund')) return '💰 Refund';
                if (intent.includes('cancel')) return '🚫 Cancel Sub';
                if (intent.includes('progress')) return '💾 Lost Progress';
                if (intent.includes('account')) return '🔐 Account';
                if (intent.includes('performance')) return '⚡ Performance';
                if (intent.includes('feature')) return '✨ Feature';
                if (intent.includes('migration')) return '📱 Migration';
                if (intent.includes('monetization') || intent.includes('complaint')) return '💸 Monetization';
                if (intent.includes('gameplay') && !intent.includes('beta')) return '🎮 Gameplay';
                return '📋 Support';
              };

              return (
                <div key={r.id} className={`border rounded-lg p-3 ${getIntentColor()} ${r.__new ? 'ring-2 ring-green-400 shadow-lg' : ''} transition-all`}>
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1 flex-wrap">
                        {dismissedIds.has(r.id) && (
                          <span className="px-2 py-1 text-xs font-bold rounded-full bg-gray-400 text-white">
                            ✓ DONE
                          </span>
                        )}
                        {r.__new && !dismissedIds.has(r.id) && (
                          <span className="px-2 py-1 text-xs font-bold rounded-full bg-green-500 text-white animate-pulse">
                            ✨ NEW
                        </span>
                      )}
                        <span className={`px-2 py-0.5 rounded-full text-xs font-semibold text-white ${
                      r.severity_bucket === 'critical' ? 'bg-red-600' :
                      r.severity_bucket === 'high' ? 'bg-orange-500' :
                          r.severity_bucket === 'medium' ? 'bg-blue-500' : 'bg-green-500'
                        }`}>
                          {(r.severity_bucket || 'low').toUpperCase()}
                      </span>
                        <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-white border border-gray-300">
                          {getIntentLabel()}
                        </span>
                        <span className="text-xs font-semibold text-gray-700">#{r.number}</span>
                        {r.similar_count > 1 && (
                          <span className="px-2 py-0.5 rounded-full text-xs bg-white border border-gray-400 font-semibold">
                            {r.similar_count} similar
                      </span>
                        )}
                        {/* Show all unique tags with distinct colors */}
                    {(r.suggested_tags || [])
                          .filter((t: string) => !t.startsWith('sev:') && !t.startsWith('intent:'))
                          .slice(0, 8)
                      .map((t: string) => {
                            const lower = t.toLowerCase();
                            let color = 'bg-gray-100 text-gray-700 border border-gray-200';
                            let label = t;
                            
                            if (lower.includes('crash')) {
                              color = 'bg-red-100 text-red-800 border border-red-300 font-semibold';
                              label = '🔥 Crash';
                            } else if (lower.includes('how_to') || lower.includes('how to')) {
                              color = 'bg-blue-100 text-blue-800 border border-blue-300 font-semibold';
                              label = '❓ How-To';
                            } else if (lower.includes('progress') || lower.includes('lost')) {
                              color = 'bg-purple-100 text-purple-800 border border-purple-300 font-semibold';
                              label = '💾 Progress Lost';
                            } else if (lower.includes('item') && (lower.includes('stuck') || lower.includes('disappeared'))) {
                              color = 'bg-rose-100 text-rose-800 border border-rose-300 font-semibold';
                              label = lower.includes('stuck') ? '🎯 Item Stuck' : '👻 Item Gone';
                            } else if (lower.includes('freeze')) {
                              color = 'bg-cyan-100 text-cyan-800 border border-cyan-300 font-semibold';
                              label = '❄️ Freeze';
                            } else if (lower.includes('store')) {
                              color = 'bg-amber-100 text-amber-800 border border-amber-300 font-semibold';
                              label = '🏪 Store Issue';
                            } else if (lower.includes('purchase') || lower.includes('payment')) {
                              color = 'bg-yellow-100 text-yellow-800 border border-yellow-300 font-semibold';
                              label = '💳 Payment';
                            } else if (lower.includes('ux')) {
                              color = 'bg-orange-100 text-orange-700 border border-orange-200';
                              label = '🎨 UX';
                            } else if (lower.includes('restart')) {
                              color = 'bg-indigo-100 text-indigo-700 border border-indigo-200';
                              label = '🔄 Restart';
                            } else if (lower.includes('flowers') || lower === 'flowers') {
                              color = 'bg-pink-100 text-pink-700 border border-pink-200';
                              label = '🌸 Flowers';
                            }
                            
                        return (
                          <span key={t} className={`px-2 py-0.5 rounded-full text-xs ${color}`}>
                                {label}
                          </span>
                        );
                      })}
                      </div>
                      <div className="text-sm font-semibold text-gray-900 mb-1">{r.subject || 'No subject'}</div>
                      {r.one_liner && (
                        <div className="text-xs text-gray-700 mb-1">{r.one_liner}</div>
                      )}
                      <div className="flex items-center gap-3 text-xs text-gray-600 flex-wrap">
                        {r.customer_name && <span>👤 {r.customer_name}</span>}
                        {r.distinct_id && (
                          <span className="px-2 py-0.5 rounded bg-gray-100 font-mono text-gray-800">
                            ID: {r.distinct_id}
                          </span>
                        )}
                        {r.entities?.platform && <span>📱 {r.entities.platform}</span>}
                        {r.entities?.app_version && <span>🔢 v{r.entities.app_version}</span>}
                        {r.updated_at && <span>🕐 {new Date(r.updated_at).toLocaleString()}</span>}
                  </div>
                </div>
                    <div className="flex-shrink-0 flex flex-col gap-2">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => markAsSeen(r.id)}
                          className={`p-2 rounded-lg transition-colors ${
                            dismissedIds.has(r.id)
                              ? 'bg-green-100 text-green-700 border border-green-300'
                              : 'bg-gray-100 text-gray-400 border border-gray-200 hover:bg-gray-200 hover:text-gray-600'
                          }`}
                          title={dismissedIds.has(r.id) ? 'Mark as not done' : 'Mark as done'}
                        >
                          {dismissedIds.has(r.id) ? '✓' : '○'}
                        </button>
                    {r.hs_link && (
                          <a
                            href={r.hs_link}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 px-3 py-2 bg-purple-600 text-white text-xs font-semibold rounded-lg hover:bg-purple-700 transition-colors"
                          >
                            Open →
                          </a>
                    )}
                  </div>
                      <button
                        onClick={() => setFeedbackTicket(r)}
                        className="px-2 py-1 bg-blue-50 text-blue-700 text-xs rounded border border-blue-200 hover:bg-blue-100 transition-colors"
                      >
                        🏷️ Fix Tags
                      </button>
                </div>
              </div>
            </div>
              );
            })}
        </div>
      </div>

    </div>
  );
};

export default Dashboard;
