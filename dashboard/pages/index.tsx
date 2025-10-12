import Link from 'next/link';
import { LayoutDashboard, Layers, MessageSquare, AlertTriangle } from 'lucide-react';

export default function Home() {
  return (
    <main className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900">HS Trends</h1>
        <p className="text-gray-600 mt-2">Navigate to any section:</p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-8">
          <Link href="/dashboard" className="group block bg-white rounded-lg p-5 shadow-sm border border-gray-100 hover:shadow transition">
            <div className="flex items-center gap-3">
              <LayoutDashboard className="w-5 h-5 text-purple-600" />
              <div>
                <div className="font-medium text-gray-900">Dashboard</div>
                <div className="text-sm text-gray-500">Visual overview with charts</div>
              </div>
            </div>
          </Link>

          <Link href="/aggregates" className="group block bg-white rounded-lg p-5 shadow-sm border border-gray-100 hover:shadow transition">
            <div className="flex items-center gap-3">
              <Layers className="w-5 h-5 text-blue-600" />
              <div>
                <div className="font-medium text-gray-900">Aggregates</div>
                <div className="text-sm text-gray-500">Clustered topics summary</div>
              </div>
            </div>
          </Link>

          <Link href="/conversations" className="group block bg-white rounded-lg p-5 shadow-sm border border-gray-100 hover:shadow transition">
            <div className="flex items-center gap-3">
              <MessageSquare className="w-5 h-5 text-green-600" />
              <div>
                <div className="font-medium text-gray-900">Conversations</div>
                <div className="text-sm text-gray-500">Recent support threads</div>
              </div>
            </div>
          </Link>

          <Link href="/incidents" className="group block bg-white rounded-lg p-5 shadow-sm border border-gray-100 hover:shadow transition">
            <div className="flex items-center gap-3">
              <AlertTriangle className="w-5 h-5 text-red-600" />
              <div>
                <div className="font-medium text-gray-900">Incidents</div>
                <div className="text-sm text-gray-500">Detections and status</div>
              </div>
            </div>
          </Link>
        </div>
      </div>
    </main>
  );
}
