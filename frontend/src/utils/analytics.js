// Utility functions for analytics calculations

export const calculateCallMetrics = (sessions) => {
  if (!sessions || sessions.length === 0) return {};

  const totalSessions = sessions.length;
  const completedCalls = sessions.filter(s => s.status === 'completed').length;
  const abandonedCalls = sessions.filter(s => s.status === 'abandoned').length;
  const failedCalls = sessions.filter(s => s.status === 'failed').length;

  const totalDuration = sessions.reduce((sum, s) => sum + s.duration_seconds, 0);
  const avgDuration = totalDuration / totalSessions;

  const successRate = (completedCalls / totalSessions) * 100;
  const abandonmentRate = (abandonedCalls / totalSessions) * 100;

  return {
    totalSessions,
    completedCalls,
    abandonedCalls,
    failedCalls,
    totalDuration,
    avgDuration,
    successRate,
    abandonmentRate
  };
};

export const getHourlyDistribution = (sessions) => {
  const hourlyData = Array(24).fill(0);

  sessions.forEach(session => {
    const hour = new Date(session.started_at).getHours();
    hourlyData[hour]++;
  });

  return hourlyData;
};

export const getDailyDistribution = (sessions) => {
  const dailyData = {};

  sessions.forEach(session => {
    const date = new Date(session.started_at).toLocaleDateString();
    dailyData[date] = (dailyData[date] || 0) + 1;
  });

  return dailyData;
};

export const getCallDurationDistribution = (sessions) => {
  const ranges = {
    '0-30s': 0,
    '31-60s': 0,
    '1-2min': 0,
    '2-5min': 0,
    '5min+': 0
  };

  sessions.forEach(session => {
    const duration = session.duration_seconds;
    if (duration <= 30) ranges['0-30s']++;
    else if (duration <= 60) ranges['31-60s']++;
    else if (duration <= 120) ranges['1-2min']++;
    else if (duration <= 300) ranges['2-5min']++;
    else ranges['5min+']++;
  });

  return ranges;
};

export const getTranscriptInsights = (transcripts) => {
  if (!transcripts || transcripts.length === 0) return {
    totalConversations: 0,
    totalLines: 0,
    agentLines: 0,
    userLines: 0,
    avgWordsPerConversation: 0,
    agentTalkRatio: 0,
    userTalkRatio: 0
  };

  const totalConversations = transcripts.length;
  let totalAgentLines = 0;
  let totalUserLines = 0;
  let totalWords = 0;

  transcripts.forEach(transcript => {
    const agentLines = (transcript.transcript.match(/Agent:/g) || []).length;
    const userLines = (transcript.transcript.match(/User:/g) || []).length;
    const words = transcript.transcript.split(/\s+/).length;
    
    totalAgentLines += agentLines;
    totalUserLines += userLines;
    totalWords += words;
  });

  const totalLines = totalAgentLines + totalUserLines;
  
  return {
    totalConversations,
    totalLines,
    agentLines: totalAgentLines,
    userLines: totalUserLines,
    avgWordsPerConversation: Math.round(totalWords / totalConversations),
    agentTalkRatio: totalLines > 0 ? (totalAgentLines / totalLines) * 100 : 0,
    userTalkRatio: totalLines > 0 ? (totalUserLines / totalLines) * 100 : 0
  };
};

export const formatDuration = (seconds) => {
  const totalSeconds = Math.floor(seconds);

  if (totalSeconds < 60) return `${totalSeconds}s`;

  const minutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;

  if (minutes < 60) {
    return remainingSeconds > 0
      ? `${minutes}m ${remainingSeconds}s`
      : `${minutes}m`;
  }

  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;

  return remainingMinutes > 0
    ? `${hours}h ${remainingMinutes}m`
    : `${hours}h`;
};


export const formatPercentage = (value, decimals = 1) => {
  return `${value.toFixed(decimals)}%`;
};

export const getTopCallers = (sessions) => {
  const callerStats = {};

  sessions.forEach(session => {
    const phone = session.phone_number;
    if (!callerStats[phone]) {
      callerStats[phone] = {
        phone,
        callCount: 0,
        totalDuration: 0,
        completedCalls: 0,
        lastCall: session.started_at
      };
    }

    callerStats[phone].callCount++;
    callerStats[phone].totalDuration += session.duration_seconds;
    if (session.status === 'completed') {
      callerStats[phone].completedCalls++;
    }

    if (new Date(session.started_at) > new Date(callerStats[phone].lastCall)) {
      callerStats[phone].lastCall = session.started_at;
    }
  });

  return Object.values(callerStats)
    .sort((a, b) => b.callCount - a.callCount)
    .slice(0, 10);
};