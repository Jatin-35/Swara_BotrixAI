import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
  ArcElement,
  PointElement,
  LineElement,
  TimeScale,
  Filler
} from "chart.js";
import { Bar, Pie, Doughnut, Line } from "react-chartjs-2";
import { TrendingUp, Clock, Phone, MessageSquare } from "lucide-react";

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
  ArcElement,
  PointElement,
  LineElement,
  TimeScale,
  Filler
);

export default function CallAnalytics({ data }) {
  // Safety checks
  if (!data || !data.summary || !data.data) {
    return (
      <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-6">
        <p className="text-sm text-yellow-800 dark:text-yellow-200">
          ⚠️ Insufficient data for analytics. Please fetch call data.
        </p>
      </div>
    );
  }

  const { summary, data: callData } = data;

  if (!callData.call_sessions || callData.call_sessions.length === 0) {
    return (
      <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-6">
        <p className="text-sm text-blue-800 dark:text-blue-200">
          ℹ️ No call sessions found for the selected date range.
        </p>
      </div>
    );
  }

  const isDark =
    typeof window !== "undefined" &&
    document.documentElement.classList.contains("dark");

  const textColor = isDark ? "#ffffff" : "#374151";
  const gridColor = isDark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.05)";

  // Status
  // Color by status MEANING (not position) so completed is always green,
  // not_connected always red — regardless of the order they arrive in.
  const STATUS_COLORS = {
    completed:     "#10B981",  // green  — success
    connected:     "#10B981",  // green
    not_connected: "#EF4444",  // red    — no answer / not connected
    failed:        "#DC2626",  // dark red
    initiated:     "#F59E0B",  // amber  — in flight
    in_progress:   "#3B82F6",  // blue
  };
  const _statusLabels = Object.keys(summary.calls_by_status || {});
  const statusData = {
    labels: _statusLabels,
    datasets: [
      {
        data: Object.values(summary.calls_by_status || {}),
        backgroundColor: _statusLabels.map(s => STATUS_COLORS[s] || "#8B5CF6"),
        borderWidth: 0
      }
    ]
  };

  // Direction
  const directionData = {
    labels: Object.keys(summary.calls_by_direction),
    datasets: [
      {
        data: Object.values(summary.calls_by_direction),
        backgroundColor: ["#3B82F6", "#06B6D4"],
        borderWidth: 0
      }
    ]
  };

  // Duration
  const durationData = {
    labels: callData.call_sessions.map(session =>
      new Date(session.started_at).toLocaleDateString()
    ),
    datasets: [
      {
        label: "Call Duration (seconds)",
        data: callData.call_sessions.map(session => session.duration_seconds),
        backgroundColor: "rgba(59, 130, 246, 0.5)",
        borderColor: "rgb(59, 130, 246)",
        borderWidth: 2
      }
    ]
  };

  // Hourly Calls
  const hourlyDistribution = callData.call_sessions.reduce((acc, session) => {
    const hour = new Date(session.started_at).getHours();
    acc[hour] = (acc[hour] || 0) + 1;
    return acc;
  }, {});

  const hourlyData = {
    labels: Array.from({ length: 24 }, (_, i) => `${i}:00`),
    datasets: [
      {
        label: "Calls per Hour",
        data: Array.from({ length: 24 }, (_, i) => hourlyDistribution[i] || 0),
        backgroundColor: "rgba(16, 185, 129, 0.5)",
        borderColor: "rgb(16, 185, 129)",
        borderWidth: 2
      }
    ]
  };

  // Speaker Distribution - analyze transcript text for Agent/User distribution
  const speakerStats = callData.transcripts.reduce((acc, transcript) => {
    const agentLines = (transcript.transcript.match(/Agent:/g) || []).length;
    const userLines = (transcript.transcript.match(/User:/g) || []).length;
    acc.agent = (acc.agent || 0) + agentLines;
    acc.user = (acc.user || 0) + userLines;
    return acc;
  }, {});

  const speakerData = {
    labels: Object.keys(speakerStats).map(s => s.charAt(0).toUpperCase() + s.slice(1)),
    datasets: [
      {
        data: Object.values(speakerStats),
        backgroundColor: ["#8B5CF6", "#F59E0B"],
        borderWidth: 0
      }
    ]
  };

  // Success Rate
  const dailyStats = callData.call_sessions.reduce((acc, session) => {
    const date = new Date(session.started_at).toLocaleDateString();
    if (!acc[date]) acc[date] = { total: 0, completed: 0 };
    acc[date].total++;
    if (session.status === "completed") acc[date].completed++;
    return acc;
  }, {});

  const successRateData = {
    labels: Object.keys(dailyStats),
    datasets: [
      {
        label: "Success Rate (%)",
        data: Object.values(dailyStats).map(
          stat => ((stat.completed / stat.total) * 100).toFixed(1)
        ),
        backgroundColor: "rgba(34, 197, 94, 0.5)",
        borderColor: "rgb(34, 197, 94)",
        borderWidth: 2,
        fill: true
      }
    ]
  };

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        labels: { color: textColor },
        position: "bottom"
      }
    },
    scales: {
      x: {
        ticks: { color: textColor },
        grid: { color: gridColor }
      },
      y: {
        ticks: { color: textColor },
        grid: { color: gridColor }
      }
    }
  };

  const pieOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        labels: { color: textColor },
        position: "bottom"
      }
    }
  };

  return (
    <div className="space-y-8">
      {/* CARDS */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {/* Success */}
        <div className="bg-gradient-to-r from-blue-500 to-blue-600 rounded-lg p-6 text-white">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-blue-100 text-sm">Success Rate</p>
              <p className="text-2xl font-bold">
                {
                  summary.total_calls > 0
                    ? ((summary.completed_calls / summary.total_calls) * 100).toFixed(1)
                    : "0.0"
                }
                %
              </p>
            </div>
            <TrendingUp className="h-8 w-8 text-blue-200" />
          </div>
        </div>

        {/* Duration */}
        <div className="bg-gradient-to-r from-green-500 to-green-600 rounded-lg p-6 text-white">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-green-100 text-sm">Avg Talk Time</p>
              <p className="text-2xl font-bold">
                {(() => {
                  const totalSeconds = Math.floor(summary.avg_duration_seconds);
                  const minutes = Math.floor(totalSeconds / 60);
                  const seconds = totalSeconds % 60;

                  return `${minutes}m ${seconds}s`;
                })()}
              </p>

            </div>
            <Clock className="h-8 w-8 text-green-200" />
          </div>
        </div>

        {/* Total Duration */}
        <div className="bg-gradient-to-r from-purple-500 to-purple-600 rounded-lg p-6 text-white">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-purple-100 text-sm">Total Duration</p>
              <p className="text-2xl font-bold">
                {(() => {
                  const totalSeconds = Math.floor(summary.total_duration_seconds);
                  const minutes = Math.floor(totalSeconds / 60);
                  return `${minutes}m`;
                })()}
              </p>
            </div>
            <Phone className="h-8 w-8 text-purple-200" />
          </div>
        </div>

        {/* Total Transcripts */}
        <div className="bg-gradient-to-r from-orange-500 to-orange-600 rounded-lg p-6 text-white">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-orange-100 text-sm">Total Transcripts</p>
              <p className="text-2xl font-bold">
                {callData.total_transcripts || 0}
              </p>
            </div>
            <MessageSquare className="h-8 w-8 text-orange-200" />
          </div>
        </div>
      </div>

      {/* CHARTS GRID */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <div className="bg-white dark:bg-gray-900 p-6 rounded-lg shadow-sm border dark:border-gray-700">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            Call Status Distribution
          </h3>
          <div className="h-64">
            <Doughnut data={statusData} options={pieOptions} />
          </div>
        </div>

        <div className="bg-white dark:bg-gray-900 p-6 rounded-lg shadow-sm border dark:border-gray-700">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            Call Direction
          </h3>
          <div className="h-64">
            <Pie data={directionData} options={pieOptions} />
          </div>
        </div>

        <div className="bg-white dark:bg-gray-900 p-6 rounded-lg shadow-sm border dark:border-gray-700">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            Call Duration Analysis
          </h3>
          <div className="h-64">
            <Bar data={durationData} options={chartOptions} />
          </div>
        </div>

        <div className="bg-white dark:bg-gray-900 p-6 rounded-lg shadow-sm border dark:border-gray-700">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            Calls by Hour
          </h3>
          <div className="h-64">
            <Line data={hourlyData} options={chartOptions} />
          </div>
        </div>

        <div className="bg-white dark:bg-gray-900 p-6 rounded-lg shadow-sm border dark:border-gray-700">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            Speaker Distribution
          </h3>
          <div className="h-64">
            <Doughnut data={speakerData} options={pieOptions} />
          </div>
        </div>

        <div className="bg-white dark:bg-gray-900 p-6 rounded-lg shadow-sm border dark:border-gray-700">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            Daily Success Rate
          </h3>
          <div className="h-64">
            <Line data={successRateData} options={chartOptions} />
          </div>
        </div>
      </div>

      {/* TABLE */}
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow-sm border dark:border-gray-700">
        <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
            Detailed Metrics
          </h3>
        </div>

        <div className="p-6">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <div className="space-y-3">
              <h4 className="font-medium text-gray-900 dark:text-white">
                Call Overview
              </h4>

              {[
                ["Total Calls", summary.total_calls],
                ["Unique Callers", summary.unique_callers],
                ["Completed Calls", summary.completed_calls],
                ["Failed Calls", summary.failed_calls]
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between text-sm">
                  <span className="text-gray-600 dark:text-gray-300">
                    {label}:
                  </span>
                  <span className="font-medium text-gray-900 dark:text-white">
                    {value}
                  </span>
                </div>
              ))}
            </div>

            <div className="space-y-3">
              <h4 className="font-medium text-gray-900 dark:text-white">
                Direction
              </h4>

              <div className="text-sm space-y-2">
                <div className="flex justify-between">
                  <span className="text-gray-600 dark:text-gray-300">
                    Inbound Calls:
                  </span>
                  <span className="text-gray-900 dark:text-white font-medium">
                    {summary.inbound_calls}
                  </span>
                </div>

                <div className="flex justify-between">
                  <span className="text-gray-600 dark:text-gray-300">
                    Outbound Calls:
                  </span>
                  <span className="text-gray-900 dark:text-white font-medium">
                    {summary.outbound_calls}
                  </span>
                </div>
              </div>
            </div>

            <div className="space-y-3">
              <h4 className="font-medium text-gray-900 dark:text-white">
                Duration & Data
              </h4>

              {[
                ["Avg Duration", `${Math.floor(summary.avg_duration_seconds / 60)}m ${summary.avg_duration_seconds % 60}s`],
                ["Total Duration", `${Math.floor(summary.total_duration_seconds / 60)}m`],
                ["Total Sessions", callData.total_call_sessions || 0],
                ["Total Transcripts", callData.total_transcripts || 0]
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between text-sm">
                  <span className="text-gray-600 dark:text-gray-300">
                    {label}:
                  </span>
                  <span className="font-medium text-gray-900 dark:text-white">
                    {value}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
