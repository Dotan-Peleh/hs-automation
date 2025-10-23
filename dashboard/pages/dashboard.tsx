import React, { useState, useMemo, useEffect } from 'react';
import { LineChart, Line, BarChart, Bar, PieChart, Pie, Cell, AreaChart, Area, RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { Calendar, TrendingUp, AlertTriangle, Bug, Zap, Monitor, Mail, Filter, Activity, AlertCircle, CheckCircle, Clock } from 'lucide-react';

const Dashboard = () => {
  const [selectedTimeRange, setSelectedTimeRange] = useState('48h');
  
  // State for all dashboard data - restored
  const [data, setData] = useState({
    dailyData: [],
    categoryData: [],
      platformData: [],
    severityData: [],
      topIssues: [],
    priorityIssues: [],
  });
  const [issueAnalysis, setIssueAnalysis] = useState<any>(null);
  
  const [insightRecs, setInsightRecs] = useState<any[]>([]);
  const [toastMsg, setToastMsg] = useState<string>('');
  const [dbStats, setDbStats] = useState<any>(null);
  const [feedbackTicket, setFeedbackTicket] = useState<any>(null);
  const [globalSummary, setGlobalSummary] = useState('');
  const [dismissedIds, setDismissedIds] = useState<Set<number>>(new Set());
  const [isSubmitting, setIsSubmitting] = useState(false);

  const openFeedbackModal = (e: React.MouseEvent, ticket: any) => {
    e.preventDefault();
    setFeedbackTicket(ticket);
  };

  const parseHours = (range: string) => {
    if (range.endsWith('d')) {
      return parseInt(range.replace('d', '')) * 24;
    }
    return parseInt(range);
  };

    const base = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8080';

  const loadDashboardData = async () => {
    console.log('🚀 Fetching all dashboard data... (v2.1)');
    try {
      const hours = 96; // Fetch 96 hours of data to populate both recent and older sections
      const [recsRes, statsRes, dashboardRes, dismissedRes] = await Promise.all([
        fetch(`${base}/admin/insights?hours=${hours}&limit=200`),
        fetch(`${base}/admin/db_stats`),
        fetch(`${base}/admin/dashboard?hours=48`), // Keep dashboard stats to 48h
        fetch(`${base}/admin/ticket/dismissed`),
      ]);

      if (recsRes.ok) {
        const recsData = await recsRes.json();
        
        // On first load or when prevRecs is empty, just set all recommendations
        setInsightRecs(prevRecs => {
          // If this is the first load (no previous tickets), just use the API data WITHOUT __new flag
          if (prevRecs.length === 0) {
            const tickets = (recsData.recommendations || []).map((t:any) => ({...t, __new: false}));
            localStorage.setItem('insightRecs', JSON.stringify(tickets));
            return tickets;
          }
          
          // Otherwise, merge new tickets with existing ones
          const existingIds = new Set(prevRecs.map(r => r.conv_id));
          const newTickets = (recsData.recommendations || []).filter((r: any) => !existingIds.has(r.conv_id));
          
          if (newTickets.length > 0) {
            setToastMsg(`🔔 ${newTickets.length} new tickets arrived!`);
            setTimeout(() => setToastMsg(''), 5000);
            
            // Mark new tickets and remove the flag after 8 seconds
            setTimeout(() => {
              setInsightRecs(currentRecs => 
                currentRecs.map(rec => ({ ...rec, __new: false }))
              );
            }, 8000);
          }
          
          const merged = [...newTickets.map((t:any)=>({...t, __new: true})), ...prevRecs];
          const final = Array.from(new Map(merged.map(item => [item.conv_id, item])).values()).slice(0, 200);
          
          // Sort the list only when new data is merged
          final.sort((a:any,b:any)=> (b?.number||0)-(a?.number||0));

          localStorage.setItem('insightRecs', JSON.stringify(final));
          return final;
        });
        
        if (recsData.global_summary) setGlobalSummary(recsData.global_summary);
        if (recsData.issue_analysis) setIssueAnalysis(recsData.issue_analysis);
      }

      if (statsRes.ok) {
        setDbStats(await statsRes.json());
      }
      
      if (dismissedRes.ok) {
        const dismissedData = await dismissedRes.json();
        setDismissedIds(new Set(dismissedData.dismissed || []));
      }

      if (dashboardRes.ok) {
        const dashData = await dashboardRes.json();
        setData(dashData);
      }

      console.log('✅ Dashboard data refreshed.');
    } catch (error) {
      console.error('❌ Failed to load initial data:', error);
    }
  };
  
  useEffect(() => {
    // On mount, load from local storage for instant UI, then fetch fresh data
    try {
      const savedRecs = localStorage.getItem('insightRecs');
      if (savedRecs) {
        setInsightRecs(JSON.parse(savedRecs));
      }
    } catch (e) {}
    
    loadDashboardData();

    // Setup real-time event listener
    console.log('⚡️ Connecting to real-time event stream...');
    const es = new EventSource(`${base}/admin/events`);

    es.onopen = () => {
      console.log('✅ Real-time connection established.');
      setToastMsg('⚡️ Real-time connection active');
      setTimeout(() => setToastMsg(''), 3000);
    };

    es.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'new_message' || data.type === 'ticket_update') {
        console.log('📬 New ticket event received:', data);
        setToastMsg(`🔔 New ticket #${data.number} arrived! Refreshing...`);
        setTimeout(loadDashboardData, 1000); // Delay to ensure data is in DB
      }
    };

    es.onerror = () => {
      console.error('❌ Real-time connection failed. Please refresh manually.');
      setToastMsg('❌ Real-time connection lost');
    };

    return () => {
      es.close();
      console.log('🔌 Real-time connection closed.');
    };
  }, [selectedTimeRange]); // Reconnect if time range changes

  const manualRefresh = () => {
    setToastMsg('🔄 Refreshing data...');
    loadDashboardData();
  };

  // Submit tag correction feedback
  const submitFeedback = async (convId: number, correctIntent: string, correctSeverity: string, notes: string) => {
    const base = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8080';
    setIsSubmitting(true);
    try {
      const params = new URLSearchParams({
        conv_id: convId.toString(),
        correct_intent: correctIntent,
        correct_severity: correctSeverity,
        notes: notes,
      });
      const response = await fetch(`${base}/admin/ticket/feedback?${params.toString()}`, {
        method: 'POST',
      });
      
      const result = await response.json();
      
      // IMMEDIATELY update the ticket in UI with corrected values
      if (result.updated_ticket) {
        const updatedRecs = insightRecs.map(rec => {
          if (rec.conv_id === convId) {
            const newRec = { ...rec };
            newRec.intent = correctIntent || rec.intent;
            newRec.severity_bucket = correctSeverity || rec.severity_bucket;
            if (correctIntent) {
              const newSuggestedTags = (rec.suggested_tags || []).filter((t: string) => !t.startsWith('intent:'));
              newSuggestedTags.unshift(`intent:${correctIntent}`);
              newRec.suggested_tags = newSuggestedTags;
            }
            if (correctSeverity) {
              const newSuggestedTags = (newRec.suggested_tags || rec.suggested_tags || []).filter((t: string) => !t.startsWith('sev:'));
              newSuggestedTags.unshift(`sev:${correctSeverity}`);
              newRec.suggested_tags = newSuggestedTags;
            }
            return newRec;
          }
          return rec;
        });
        setInsightRecs(updatedRecs);
        localStorage.setItem('insightRecs', JSON.stringify(updatedRecs)); // Persist changes
      }
      
      setToastMsg('✅ Tags updated instantly! Model learned from your correction.');
      setTimeout(() => setToastMsg(''), 4000);
      setFeedbackTicket(null);
    } catch (e) {
      console.error('Failed to submit feedback:', e);
      setToastMsg('❌ Failed to save feedback');
      setTimeout(() => setToastMsg(''), 3000);
    } finally {
        setIsSubmitting(false);
    }
  };

  // Mark ticket as done/seen (toggle) - INSTANT UI UPDATE
  const markAsSeen = async (convId: number) => {
    const isDismissed = dismissedIds.has(convId);
    
    // Optimistic UI update
    const newSet = new Set(dismissedIds);
    if (isDismissed) {
      newSet.delete(convId);
      setToastMsg('↩️ Ticket unmarked');
    } else {
      newSet.add(convId);
      setToastMsg('✅ Ticket marked as done');
    }
    setDismissedIds(newSet);
    setTimeout(() => setToastMsg(''), 2000);
    
    // THEN sync with server in background
    try {
      if (isDismissed) {
        await fetch(`${base}/admin/ticket/unmark?conv_id=${convId}`, {
          method: 'POST',
        });
      } else {
        const params = new URLSearchParams({
          conv_id: convId.toString(),
          action: 'dismissed',
        });
        await fetch(`${base}/admin/ticket/mark_seen?${params.toString()}`, {
          method: 'POST',
        });
      }
    } catch (e) {
      console.error('Failed to sync with server:', e);
      // Revert UI change if server call failed
      const revertedSet = new Set(dismissedIds);
      if (isDismissed) {
        revertedSet.add(convId);
      } else {
        revertedSet.delete(convId);
      }
      setDismissedIds(revertedSet);
      setToastMsg('❌ Sync failed, please try again');
    }
  };
  
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
    if (r.one_liner) return r.one_liner;
    if (r.subject) return r.subject;
    if (r.escalation_reason) return r.escalation_reason;
    return 'No description available.';
  };
  
  // Reusable TicketItem component
  const TicketItem = ({ r }: { r: any }) => {
    const isNew = useMemo(() => {
      if (!r.updated_at) return false;
      const ticketDate = new Date(r.updated_at);
      const minutesAgo = (new Date().getTime() - ticketDate.getTime()) / 60000;
      return minutesAgo < 15;
    }, [r.updated_at]);
  
    const intentTag = (r.suggested_tags || []).find((t: string) => t.startsWith('intent:'));
    const intent = intentTag ? intentTag.split(':')[1] : (r.intent || '');
    
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
      if (intent.includes('crash') || intent === 'crash_report') return '💥 Crash';
      if (intent.includes('bug')) return '🐛 Bug';
      if (intent.includes('how_to') || intent === 'question') return '❓ How-To';
      if (intent.includes('refund')) return '💰 Refund';
      if (intent.includes('cancel')) return '🚫 Cancel Sub';
      if (intent.includes('billing') || intent.includes('payment')) return '💳 Billing';
      if (intent.includes('offerwall')) return '🎁 OfferWall';
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
      <div className={`border rounded-lg p-3 ${getIntentColor()} ${isNew ? 'ring-2 ring-green-400 shadow-lg' : ''} transition-all`}>
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              {isNew && !dismissedIds.has(r.conv_id) && (
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
            </div>
            <div className="text-sm font-semibold text-gray-900 my-1">{r.subject || 'No subject'}</div>
            <div className="text-xs text-gray-700 mb-2">{r.one_liner}</div>
            <div className="flex items-center gap-3 text-xs text-gray-600 flex-wrap">
              <span className="font-semibold">👤 {r.first_name} {r.last_name}</span>
              {r.game_user_id && (
                <span className="px-2 py-0.5 rounded bg-purple-50 font-mono text-purple-700 border border-purple-200">
                  🎮 {r.game_user_id.slice(0, 8)}...{r.game_user_id.slice(-4)}
                </span>
              )}
              <span>📱 {r.entities?.platform}</span>
              <span>🔢 {r.entities?.app_version}</span>
              <span>🕐 {new Date(r.updated_at).toLocaleString()}</span>
            </div>
            <div className="flex items-center gap-1 mt-2 flex-wrap">
                {(r.existing_tags || []).map((t: string) => (
                    <span key={t} className="px-2 py-0.5 rounded-full text-xs bg-gray-200 text-gray-800 border border-gray-300">
                        {t}
                    </span>
                ))}
            </div>
          </div>
          <div className="flex-shrink-0 flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <button
                onClick={() => markAsSeen(r.conv_id)}
                className={`p-2 rounded-lg transition-colors ${
                  dismissedIds.has(r.conv_id)
                    ? 'bg-green-100 text-green-700 border border-green-300'
                    : 'bg-gray-100 text-gray-400 border border-gray-200 hover:bg-gray-200 hover:text-gray-600'
                }`}
                title={dismissedIds.has(r.conv_id) ? 'Mark as not done' : 'Mark as done'}
              >
                {dismissedIds.has(r.conv_id) ? '✓' : '○'}
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
              onClick={(e) => openFeedbackModal(e, r)}
              className="px-2 py-1 bg-blue-50 text-blue-700 text-xs rounded border border-blue-200 hover:bg-blue-100 transition-colors"
            >
              🏷️ Fix Tags
            </button>
          </div>
        </div>
      </div>
    );
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
                  <option value="crash_report">💥 Crash (App Closes/Freezes)</option>
                  <option value="bug_report">🐛 Bug (Gameplay Issue)</option>
                  <option value="billing_issue">💳 Billing/Payment Issue</option>
                  <option value="offerwall_issue">🎁 OfferWall Issue</option>
                  <option value="refund_request">💰 Refund Request</option>
                  <option value="delete_account">🚫 Delete Account / Cancel Sub</option>
                  <option value="lost_progress">💾 Lost Progress/Save Issue</option>
                  <option value="question">❓ How-To Question</option>
                  <option value="feedback">💭 Feedback/Compliment</option>
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
                    submitFeedback(feedbackTicket.conv_id, intent, severity, notes);
                  }}
                  className="flex-1 px-4 py-2 bg-blue-600 text-white font-semibold rounded-lg hover:bg-blue-700 transition-colors"
                  disabled={isSubmitting}
                >
                  {isSubmitting ? 'Submitting...' : 'Submit Feedback'}
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
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 mb-2">🎮 Game Support Dashboard</h1>
        <p className="text-gray-600">Monitor and analyze user feedback trends from support emails</p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={manualRefresh}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors flex items-center gap-2 font-semibold"
              title="Manually check for new tickets from Help Scout"
            >
              🔄 Refresh Now
            </button>
            <button
              onClick={async () => {
                setToastMsg('🔎 Fetching latest from Help Scout...');
                try {
                  const base = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8080';
                  const res = await fetch(`${base}/admin/backfill`, { method: 'POST' });
                  if (res.ok) {
                    const result = await res.json();
                    setToastMsg(`✅ Fetched ${result.saved || 0} new tickets from Help Scout`);
                    setTimeout(() => setToastMsg(''), 5000);
                    // Refresh dashboard after backfill
                    setTimeout(manualRefresh, 1000);
                  } else {
                    setToastMsg('❌ Failed to fetch from Help Scout');
                    setTimeout(() => setToastMsg(''), 3000);
                  }
                } catch (err) {
                  setToastMsg('❌ Backfill failed');
                  setTimeout(() => setToastMsg(''), 3000);
                }
              }}
              className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors flex items-center gap-2 font-semibold"
              title="Force fetch new tickets from Help Scout API"
            >
              🔎 Fetch New
            </button>
          </div>
        </div>
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
          {insightRecs.filter((r:any)=> !r.__loading && r.severity_bucket && ['critical','high'].includes(r.severity_bucket.toLowerCase()) && !dismissedIds.has(r.conv_id)).length > 0 ? (
            <div className="space-y-3">
              {insightRecs
                .filter((r:any)=> !r.__loading && r.severity_bucket && ['critical','high'].includes(r.severity_bucket.toLowerCase()) && !dismissedIds.has(r.conv_id))
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
                  if (intent.includes('crash') || intent === 'crash_report') return '💥 Crash';
                  if (intent.includes('bug')) return '🐛 Bug';
                  if (intent.includes('how_to') || intent === 'question') return '❓ How-To';
                  if (intent.includes('refund')) return '💰 Refund';
                  if (intent.includes('cancel')) return '🚫 Cancel Sub';
                  if (intent.includes('billing') || intent.includes('payment')) return '💳 Billing';
                  if (intent.includes('progress')) return '💾 Lost Progress';
                  if (intent.includes('account')) return '🔐 Account';
                  if (intent.includes('monetization') || intent.includes('complaint')) return '💸 Monetization';
                  if (intent.includes('gameplay') && !intent.includes('beta')) return '🎮 Gameplay';
                  return '📋 Support';
                };

                return (
                  <div key={r.conv_id} className={`border-2 rounded-lg p-4 ${getIntentColor()}`}>
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
                          {(r.first_name || r.last_name) && (
                            <span className="font-semibold">👤 {r.first_name} {r.last_name}</span>
                          )}
                          {r.game_user_id && (
                            <span className="px-2 py-0.5 rounded bg-purple-50 font-mono text-purple-700 border border-purple-200 text-xs">
                              🎮 {r.game_user_id.slice(0, 8)}...{r.game_user_id.slice(-4)}
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
                          onClick={() => markAsSeen(r.conv_id)}
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
        <h3 className="text-lg font-semibold text-gray-900 mb-4">📋 All Messages</h3>
        
        {/* Recent Tickets (Last 48h) */}
            <div className="space-y-3">
          <h4 className="text-md font-semibold text-gray-700 mt-4 mb-2">Recent Tickets (Last 48 Hours)</h4>
          {Array.isArray(insightRecs) ? insightRecs
            .filter((x:any) => {
              if (!x || !x.updated_at) return false;
              const ticketDate = new Date(x.updated_at);
              const hoursAgo = (new Date().getTime() - ticketDate.getTime()) / 3600000;
              return hoursAgo <= 48;
            })
            // .sort((a:any,b:any)=> (b?.number||0)-(a?.number||0)) // REMOVED: Sorting is now done on data load
            .map((r: any) => <TicketItem key={r.conv_id} r={r} />)
            : <div className="text-gray-500">Loading tickets...</div>}
        </div>

        {/* Older Tickets (Collapsible) */}
        <details className="mt-6">
          <summary className="text-md font-semibold text-gray-700 cursor-pointer bg-gray-100 p-2 rounded-lg hover:bg-gray-200">
            Older Tickets (&gt;48 Hours)
          </summary>
          <div className="space-y-3 mt-4">
            {Array.isArray(insightRecs) ? insightRecs
              .filter((x:any) => {
                if (!x || !x.updated_at) return false;
                const ticketDate = new Date(x.updated_at);
                const hoursAgo = (new Date().getTime() - ticketDate.getTime()) / 3600000;
                return hoursAgo > 48;
              })
              // .sort((a:any,b:any)=> (b?.number||0)-(a?.number||0)) // REMOVED: Sorting is now done on data load
              .map((r: any) => <TicketItem key={r.conv_id} r={r} />)
              : <div className="text-gray-500">Loading tickets...</div>}
          </div>
        </details>
      </div>

    </div>
  );
};

export default Dashboard;
