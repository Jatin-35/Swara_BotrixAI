import { 
  TrendingUp, 
  TrendingDown, 
  Users, 
  Clock, 
  Phone,
  MessageSquare,
  Target,
  AlertTriangle
} from "lucide-react";

import { 
  calculateCallMetrics, 
  getTranscriptInsights, 
  getTopCallers,
  formatDuration,
  formatPercentage 
} from "../utils/analytics";

export default function InsightsPanel({ data }) {
  const { data: callData } = data;
  const callMetrics = calculateCallMetrics(callData.call_sessions);
  const transcriptInsights = getTranscriptInsights(callData.transcripts);
  const topCallers = getTopCallers(callData.call_sessions);

  const insights = [
    {
      title: "Call Success Rate",
      value: formatPercentage(callMetrics.successRate || 0),
      icon: Target,
      trend: callMetrics.successRate > 70 ? "up" : "down",
      color: callMetrics.successRate > 70 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400",
      bgColor: callMetrics.successRate > 70 
        ? "bg-green-50 dark:bg-green-900/30" 
        : "bg-red-50 dark:bg-red-900/30",
      description: callMetrics.successRate > 70 ? "Excellent success rate" : "Needs improvement"
    },
    {
      title: "Abandonment Rate",
      value: formatPercentage(callMetrics.abandonmentRate || 0),
      icon: AlertTriangle,
      trend: callMetrics.abandonmentRate < 30 ? "up" : "down",
      color: callMetrics.abandonmentRate < 30 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400",
      bgColor: callMetrics.abandonmentRate < 30 
        ? "bg-green-50 dark:bg-green-900/30" 
        : "bg-red-50 dark:bg-red-900/30",
      description: callMetrics.abandonmentRate < 30 ? "Low abandonment" : "High abandonment"
    },
    {
      title: "Avg Call Duration",
      value: formatDuration(Math.round(callMetrics.avgDuration || 0)),
      icon: Clock,
      trend: callMetrics.avgDuration > 60 ? "up" : "down",
      color: "text-blue-600 dark:text-blue-400",
      bgColor: "bg-blue-50 dark:bg-blue-900/30",
      description: "Average talk time"
    },
    {
      title: "Agent Talk Ratio",
      value: formatPercentage(transcriptInsights.agentTalkRatio || 0),
      icon: MessageSquare,
      trend: transcriptInsights.agentTalkRatio < 70 ? "up" : "down",
      color:
        transcriptInsights.agentTalkRatio < 70
          ? "text-green-600 dark:text-green-400"
          : "text-orange-600 dark:text-orange-400",
      bgColor:
        transcriptInsights.agentTalkRatio < 70
          ? "bg-green-50 dark:bg-green-900/30"
          : "bg-orange-50 dark:bg-orange-900/30",
      description:
        transcriptInsights.agentTalkRatio < 70
          ? "Good balance"
          : "Agent talks too much"
    }
  ];

  return (
    <div className="space-y-6">
      {/* Key Insights */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {insights.map((insight, index) => {
          const Icon = insight.icon;
          const TrendIcon = insight.trend === "up" ? TrendingUp : TrendingDown;

          return (
            <div
              key={index}
              className={`${insight.bgColor} rounded-lg p-6 border border-gray-200 dark:border-gray-700 transition-colors`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center">
                  <Icon className={`h-8 w-8 ${insight.color}`} />
                  <div className="ml-3">
                    <p className="text-sm font-medium text-gray-600 dark:text-gray-400">
                      {insight.title}
                    </p>
                    <p className={`text-2xl font-bold ${insight.color}`}>
                      {insight.value}
                    </p>
                  </div>
                </div>
                <TrendIcon className={`h-5 w-5 ${insight.color}`} />
              </div>

              <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
                {insight.description}
              </p>
            </div>
          );
        })}
      </div>

      {/* Top Callers */}
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700">
        <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center">
            <Users className="h-5 w-5 mr-2" />
            Top Callers
          </h3>
        </div>

        <div className="p-6">
          {topCallers.length > 0 ? (
            <div className="space-y-4">
              {topCallers.map((caller, index) => (
                <div
                  key={caller.phone}
                  className="flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-800/50 rounded-lg"
                >
                  <div className="flex items-center space-x-3">
                    <div className="flex-shrink-0">
                      <div className="w-8 h-8 bg-blue-100 dark:bg-blue-900 rounded-full flex items-center justify-center">
                        <span className="text-sm font-medium text-blue-600 dark:text-blue-300">
                          #{index + 1}
                        </span>
                      </div>
                    </div>

                    <div>
                      <p className="text-sm font-medium text-gray-900 dark:text-white">
                        {caller.phone}
                      </p>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        Last call: {new Date(caller.lastCall).toLocaleDateString()}
                      </p>
                    </div>
                  </div>

                  <div className="text-right">
                    <div className="flex items-center space-x-4 text-sm">

                      <div className="text-center">
                        <p className="font-medium text-gray-900 dark:text-white">
                          {caller.callCount}
                        </p>
                        <p className="text-xs text-gray-500 dark:text-gray-400">calls</p>
                      </div>

                      <div className="text-center">
                        <p className="font-medium text-gray-900 dark:text-white">
                          {formatDuration(caller.totalDuration)}
                        </p>
                        <p className="text-xs text-gray-500 dark:text-gray-400">total time</p>
                      </div>

                      <div className="text-center">
                        <p className="font-medium text-gray-900 dark:text-white">
                          {formatPercentage((caller.completedCalls / caller.callCount) * 100)}
                        </p>
                        <p className="text-xs text-gray-500 dark:text-gray-400">success</p>
                      </div>

                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-500 dark:text-gray-400 text-center py-4">
              No caller data available
            </p>
          )}
        </div>
      </div>

      {/* Conversation Insights */}
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700">
        <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center">
            <MessageSquare className="h-5 w-5 mr-2" />
            Conversation Insights
          </h3>
        </div>

        <div className="p-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">

            <div className="text-center">
              <div className="text-3xl font-bold text-blue-600 dark:text-blue-400">
                {transcriptInsights.totalConversations || 0}
              </div>
              <div className="text-sm text-gray-600 dark:text-gray-400">
                Total Conversations
              </div>
            </div>

            <div className="text-center">
              <div className="text-3xl font-bold text-green-600 dark:text-green-400">
                {transcriptInsights.totalLines || 0}
              </div>
              <div className="text-sm text-gray-600 dark:text-gray-400">
                Total Messages
              </div>
            </div>

            <div className="text-center">
              <div className="text-3xl font-bold text-purple-600 dark:text-purple-400">
                {transcriptInsights.avgWordsPerConversation || 0}
              </div>
              <div className="text-sm text-gray-600 dark:text-gray-400">
                Avg Words/Conversation
              </div>
            </div>

          </div>
        </div>
      </div>
    </div>
  );
}
