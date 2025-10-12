import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/router';
import { ExternalLink, ArrowLeft, Clock, User } from 'lucide-react';

const ConversationsPage = () => {
  const router = useRouter();
  const { cluster_key, hours } = router.query;
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!cluster_key) return;
    const base = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8080';
    const hoursParam = hours || 48;
    
    fetch(`${base}/admin/cluster_conversations?cluster_key=${encodeURIComponent(cluster_key as string)}&hours=${hoursParam}`)
      .then(res => res.json())
      .then(data => {
        setData(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [cluster_key, hours]);

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 p-6">
        <div className="max-w-6xl mx-auto">
          <div className="text-gray-600">Loading...</div>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="min-h-screen bg-gray-50 p-6">
        <div className="max-w-6xl mx-auto">
          <div className="text-red-600">Failed to load conversations</div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="mb-6">
          <button
            onClick={() => router.back()}
            className="flex items-center gap-2 text-purple-600 hover:text-purple-700 mb-4"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Dashboard
          </button>
          <h1 className="text-3xl font-bold text-gray-900 mb-2">
            Related Tickets
          </h1>
          <p className="text-gray-600">
            Cluster: <span className="font-mono text-sm bg-gray-100 px-2 py-1 rounded">{data.cluster_key}</span>
          </p>
          <p className="text-gray-600 mt-1">
            {data.count} {data.count === 1 ? 'conversation' : 'conversations'} found
          </p>
        </div>

        {/* Conversations List */}
        <div className="bg-white rounded-lg shadow-sm">
          {data.conversations && data.conversations.length > 0 ? (
            <div className="divide-y">
              {data.conversations.map((conv: any) => (
                <div key={conv.id} className="p-4 hover:bg-gray-50 transition-colors">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-3 mb-2">
                        <span className="text-sm font-semibold text-purple-600">
                          #{conv.number}
                        </span>
                        <h3 className="text-lg font-medium text-gray-900 truncate">
                          {conv.subject || 'No Subject'}
                        </h3>
                      </div>
                      
                      {conv.customer_name && (
                        <div className="flex items-center gap-2 text-sm text-gray-600 mb-2">
                          <User className="w-4 h-4" />
                          <span>{conv.customer_name}</span>
                        </div>
                      )}
                      
                      {conv.text_preview && (
                        <p className="text-sm text-gray-600 mb-2 line-clamp-2">
                          {conv.text_preview}
                        </p>
                      )}
                      
                      {conv.updated_at && (
                        <div className="flex items-center gap-2 text-xs text-gray-500">
                          <Clock className="w-3 h-3" />
                          <span>
                            {new Date(conv.updated_at).toLocaleString()}
                          </span>
                        </div>
                      )}
                    </div>
                    
                    <div className="flex-shrink-0">
                      {conv.hs_link && (
                        <a
                          href={conv.hs_link}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors"
                        >
                          <span>Open in Help Scout</span>
                          <ExternalLink className="w-4 h-4" />
                        </a>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="p-8 text-center text-gray-500">
              No conversations found in this cluster
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ConversationsPage;
