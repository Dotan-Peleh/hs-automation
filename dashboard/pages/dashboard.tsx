import React, { useState, useMemo, useEffect } from 'react';
import { LineChart, Line, BarChart, Bar, PieChart, Pie, Cell, AreaChart, Area, RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { Calendar, TrendingUp, AlertTriangle, Bug, Zap, Monitor, Mail, Filter, Activity, AlertCircle, CheckCircle, Clock } from 'lucide-react';

// Generate mock data
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
      radarData: [],
    } as any;
  };
  const [data, setData] = useState(getEmptyData());
  // Insights state
  const [insightsCats, setInsightsCats] = useState<any[]>([]);
  const [insightsWords, setInsightsWords] = useState<any[]>([]);
  const [issueAnalysis, setIssueAnalysis] = useState<any | null>(null);
  const [insightRecs, setInsightRecs] = useState<any[]>([]);

  // Remove mock injection; rely on live data only

  // Fetch live backend stats for last 48h to reflect real HS data
  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8080';
    (async () => {
      try {
        // Trigger a quick delta backfill on each dashboard load
        try { await fetch(base + '/admin/backfill?limit_pages=1'); } catch {}
        const res = await fetch(base + '/admin/dashboard?hours=48');
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
        const pageSize = 50;
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
            setIssueAnalysis(j.issue_analysis || null);
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
          await new Promise(r=>setTimeout(r, 150));
        }
      } catch (_) { /* no-op */ }
    })();
    return () => { cancelled = true; };
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
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Game Support Dashboard</h1>
        <p className="text-gray-600">Monitor and analyze user feedback trends from support emails</p>
      </div>
      
      {/* Filters Bar */}
      {/* Filters/Export bar removed per request */}
      
      {/* Summary Cards removed per request */}
      
      {/* Main Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* Trend Chart */}
        <div className="bg-white rounded-lg shadow-sm p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-purple-600" />
            Issue Trends Over Time
          </h3>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={data.dailyData}>
              <defs>
                <linearGradient id="colorBugs" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#ef4444" stopOpacity={0.8}/>
                  <stop offset="95%" stopColor="#ef4444" stopOpacity={0}/>
                </linearGradient>
                <linearGradient id="colorCrashes" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#dc2626" stopOpacity={0.8}/>
                  <stop offset="95%" stopColor="#dc2626" stopOpacity={0}/>
                </linearGradient>
                <linearGradient id="colorUX" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.8}/>
                  <stop offset="95%" stopColor="#f59e0b" stopOpacity={0}/>
                </linearGradient>
                <linearGradient id="colorPayments" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#6366f1" stopOpacity={0.8}/>
                  <stop offset="95%" stopColor="#6366f1" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="ts" tick={{ fontSize: 12 }} stroke="#6b7280" tickFormatter={(v:any)=>{
                try { return new Date(v).toLocaleTimeString([], { hour: 'numeric' }); } catch { return v; }
              }} />
              <YAxis tick={{ fontSize: 12 }} stroke="#6b7280" />
              <Tooltip />
              <Area type="monotone" dataKey="bugs" stackId="1" stroke="#ef4444" fillOpacity={1} fill="url(#colorBugs)" />
              <Area type="monotone" dataKey="crashes" stackId="1" stroke="#dc2626" fillOpacity={1} fill="url(#colorCrashes)" />
              <Area type="monotone" dataKey="uxIssues" stackId="1" stroke="#f59e0b" fillOpacity={1} fill="url(#colorUX)" />
              <Area type="monotone" dataKey="payments" stackId="1" stroke="#6366f1" fillOpacity={1} fill="url(#colorPayments)" />
              <Legend />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        
        {/* Category Distribution removed per request */}
      </div>
      
      {/* Secondary Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
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
        
        {/* Response Time Distribution */}
        <div className="bg-white rounded-lg shadow-sm p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <Clock className="w-5 h-5 text-purple-600" />
            Response Times
          </h3>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={data.responseTimeData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="hour" tick={{ fontSize: 12 }} stroke="#6b7280" />
              <YAxis tick={{ fontSize: 12 }} stroke="#6b7280" />
              <Tooltip />
              <Line type="monotone" dataKey="count" stroke="#8b5cf6" strokeWidth={2} dot={{ fill: '#8b5cf6', r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
      
      {/* Message Recommendations moved above analytical charts */}
      

      {/* Issue Pattern Radar & Priority Issue */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Issue Pattern Radar */}
        <div className="bg-white rounded-lg shadow-sm p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <Zap className="w-5 h-5 text-purple-600" />
            Issue Pattern Analysis
          </h3>
          <ResponsiveContainer width="100%" height={300}>
            <RadarChart data={data.radarData}>
              <PolarGrid stroke="#e5e7eb" />
              <PolarAngleAxis dataKey="aspect" tick={{ fontSize: 12 }} stroke="#6b7280" />
              <PolarRadiusAxis angle={90} domain={[0, 100]} tick={{ fontSize: 12 }} stroke="#6b7280" />
              <Radar name="Current Week" dataKey="current" stroke="#8b5cf6" fill="#8b5cf6" fillOpacity={0.6} />
              <Radar name="Previous Week" dataKey="previous" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.6} />
              <Legend />
              <Tooltip />
            </RadarChart>
          </ResponsiveContainer>
        </div>
        
        {/* Priority Issues (top 5 with category escalation) */}
        <div className="bg-white rounded-lg shadow-sm p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <AlertCircle className="w-5 h-5 text-purple-600" />
            Priority Issues (last 48h)
          </h3>
          {(data.priorityIssues && data.priorityIssues.length) ? (
            <div className="space-y-3">
              {data.priorityIssues.slice(0,5).map((pi:any)=> (
                <div key={pi.id} className="border rounded-lg p-4">
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium text-white ${
                      (pi.severity || '').toLowerCase() === 'critical' ? 'bg-red-600' :
                      (pi.severity || '').toLowerCase() === 'high' ? 'bg-orange-500' :
                      (pi.severity || '').toLowerCase() === 'medium' ? 'bg-blue-500' : 'bg-green-500'
                    }`}>
                      {(pi.severity || 'medium').toString().toUpperCase()}
                    </span>
                    <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full">{pi.category}</span>
                    {pi.occurrences != null && (
                      <span className="text-xs text-gray-500">{pi.occurrences} related tickets</span>
                    )}
                  </div>
                  <div className="text-sm font-medium text-gray-900 mb-1">{pi.title}</div>
                  {pi.last_seen && (
                    <div className="text-xs text-gray-400">Last seen: {new Date(pi.last_seen).toLocaleString()}</div>
                  )}
                  <div className="mt-2">
                    <a
                      href={`${process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8080'}/admin/cluster_conversations?cluster_key=${encodeURIComponent(pi.id)}&hours=48`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-purple-600 hover:underline text-sm"
                    >
                      View related tickets
                    </a>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm text-gray-500">No high-priority issues in the last 48 hours.</div>
          )}
        </div>
      </div>

      {/* Insights (Claude) */}
      <div className="mt-8 grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="bg-white rounded-lg shadow-sm p-6 lg:col-span-1">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Insights: Top Categories (24h)</h3>
          <div className="space-y-2">
            {insightsCats.slice(0, 10).map((c: any) => (
              <div key={c.name} className="flex items-center justify-between text-sm">
                <span className="text-gray-700 capitalize">{String(c.name).replace(/_/g,' ')}</span>
                <span className="text-gray-500">{c.count}</span>
              </div>
            ))}
            {!insightsCats?.length && (<div className="text-sm text-gray-500">No data yet</div>)}
          </div>
        </div>

        <div className="bg-white rounded-lg shadow-sm p-6 lg:col-span-2">
          <h3 className="text-lg font-semibold text-gray-900 mb-2">Insights: Issue Analysis (24h)</h3>
          {!issueAnalysis && (
            <div className="text-sm text-gray-500">No data yet</div>
          )}
          {issueAnalysis && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <div className="text-sm font-medium text-gray-700 mb-1">Intents</div>
                <div className="space-y-1">
                  {(issueAnalysis.intents || []).slice(0,6).map((i:any)=> (
                    <div key={i.name} className="flex items-center justify-between text-sm">
                      <span className="capitalize text-gray-700">{String(i.name).replace(/_/g,' ')}</span>
                      <span className="text-gray-500">{i.count}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <div className="text-sm font-medium text-gray-700 mb-1">Platforms</div>
                <div className="space-y-1">
                  {(issueAnalysis.platforms || []).slice(0,6).map((p:any)=> (
                    <div key={p.name} className="flex items-center justify-between text-sm">
                      <span className="capitalize text-gray-700">{p.name}</span>
                      <span className="text-gray-500">{p.count}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <div className="text-sm font-medium text-gray-700 mb-1">Severities</div>
                <div className="space-y-1">
                  {(issueAnalysis.severities || []).map((s:any)=> (
                    <div key={s.bucket} className="flex items-center justify-between text-sm">
                      <span className="text-gray-700">{s.bucket}</span>
                      <span className="text-gray-500">{s.count}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="mt-6 bg-white rounded-lg shadow-sm p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Message Recommendations (Claude)</h3>
        <div className="divide-y">
          {(!insightRecs?.length || insightRecs[0]?.__loading) && (
            <div className="py-3 text-sm text-gray-500 flex items-center gap-2">
              <svg className="animate-spin h-4 w-4 text-gray-400" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"></path></svg>
              <span>{insightRecs[0]?.__progress || 'Loading messages…'}</span>
            </div>
          )}
          {insightRecs
            .filter((x:any)=>!x.__loading)
            .sort((a:any,b:any)=> (b.number||0)-(a.number||0))
            .slice(0, 20)
            .map((r: any) => (
            <div key={r.id} className="py-3">
              <div className="flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <div className="text-sm font-medium text-gray-900 truncate">#{r.number} — {r.subject || 'No subject'}</div>
                  {(r.customer_name || (r.tags && String(r.tags).includes('user:'))) && (
                    <div className="text-xs text-gray-500 mt-0.5">{r.customer_name || String(r.tags).split(',').find((t:string)=>t.startsWith('user:'))?.replace('user:','').trim()}</div>
                  )}
                  <div className="text-sm text-gray-600 mt-1">{r.one_liner || (r.intent ? r.intent.replace(/_/g,' ') : '') || r.summary || getShortDescription(r)}</div>
                  <div className="flex flex-wrap gap-2 mt-2">
                    <span className={`px-2 py-0.5 rounded-full text-xs text-white ${
                      r.severity_bucket === 'critical' ? 'bg-red-600' :
                      r.severity_bucket === 'high' ? 'bg-orange-500' :
                      r.severity_bucket === 'low' ? 'bg-green-500' : 'bg-blue-500'
                    }`}>{(r.severity_bucket || 'medium').toString().toUpperCase()}</span>
                    {(r.categories || []).slice(0, 6).map((c: string) => (
                      <span key={c} className="px-2 py-0.5 rounded-full text-xs bg-purple-50 text-purple-700">
                        {c.replace(/_/g,' ')}
                      </span>
                    ))}
                    {(r.suggested_tags || [])
                      .filter((t: string) => !/^cat:(uncategorized|device)$/i.test(t))
                      .filter((t: string) => !/^sev:(low|medium|high)$/i.test(t))
                      .filter((t: string) => !/^platform:/i.test(t))
                      .slice(0, 10)
                      .map((t: string) => {
                        const lower = String(t).toLowerCase();
                        const color =
                          lower.startsWith('sev:critical') ? 'bg-red-600 text-white' :
                          lower.startsWith('sev:high') ? 'bg-orange-500 text-white' :
                          lower.startsWith('sev:medium') ? 'bg-blue-100 text-blue-700' :
                          lower.startsWith('sev:low') ? 'bg-green-100 text-green-700' :
                          lower.startsWith('tag:crash') || lower.includes('crash') ? 'bg-red-100 text-red-700' :
                          lower.startsWith('intent:how_to') || lower.includes('how_to') ? 'bg-indigo-100 text-indigo-700' :
                          lower.startsWith('intent:refund_request') ? 'bg-yellow-100 text-yellow-800' :
                          lower.startsWith('intent:cancel_subscription') ? 'bg-rose-100 text-rose-700' :
                          lower.startsWith('intent:bug_report') ? 'bg-red-100 text-red-700' :
                          lower.startsWith('intent:performance_issue') ? 'bg-purple-100 text-purple-700' :
                          lower.startsWith('intent:feature_request') ? 'bg-teal-100 text-teal-700' :
                          lower.startsWith('intent:device_migration') ? 'bg-sky-100 text-sky-700' :
                          lower.startsWith('platform:') ? 'bg-gray-100 text-gray-700' :
                          'bg-gray-100 text-gray-700';
                        return (
                          <span key={t} className={`px-2 py-0.5 rounded-full text-xs ${color}`}>
                            {t}
                          </span>
                        );
                      })}
                    {r.intent && (
                      <span className="px-2 py-0.5 rounded-full text-xs bg-blue-50 text-blue-700">intent:{r.intent}</span>
                    )}
                    {(r.entities?.platform) && (
                      <span className="px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-700">{r.entities.platform}</span>
                    )}
                    {(r.entities?.app_version) && (
                      <span className="px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-700">v{r.entities.app_version}</span>
                    )}
                    {(typeof r.entities?.level === 'number') && (
                      <span className="px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-700">lvl {r.entities.level}</span>
                    )}
                  </div>
                </div>
                <div className="text-right text-xs text-gray-500 shrink-0 flex flex-col items-end gap-1">
                  <span>{r.updated_at ? new Date(r.updated_at).toLocaleString() : ''}</span>
                  <div className="flex gap-2">
                    {r.hs_link && (
                      <a href={r.hs_link} target="_blank" rel="noreferrer" className="text-purple-600 hover:underline">Open in Help Scout</a>
                    )}
                    {r.api_link && (
                      <a href={r.api_link} target="_blank" rel="noreferrer" className="text-gray-600 hover:underline">API</a>
                    )}
                    {typeof r.similar_count === 'number' && r.similar_count > 1 && (
                      <span className="ml-2 text-gray-500">Similar: {r.similar_count}</span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))}
          {!insightRecs?.length && (<div className="text-sm text-gray-500">No messages analyzed yet</div>)}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
