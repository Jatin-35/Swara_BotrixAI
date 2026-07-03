import { MessageSquare, Clock, Phone, Search } from "lucide-react";
import { useState } from "react";
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export default function TranscriptsTable({ transcripts }) {
  const [searchTerm, setSearchTerm] = useState("");

  // Filter transcripts by search
  const filteredTranscripts = transcripts.filter((t) => {
    const matchesSearch = 
      t.transcript.toLowerCase().includes(searchTerm.toLowerCase()) ||
      t.phone_number.includes(searchTerm) ||
      t.call_id.toLowerCase().includes(searchTerm.toLowerCase());
    return matchesSearch;
  });

  // Format timestamp
  const formatTimestamp = (timestamp) => {
    const date = new Date(timestamp);
    return {
      date: date.toLocaleDateString(),
      time: date.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      }),
    };
  };

  // Parse transcript to extract speakers and format better
  const parseTranscript = (transcript) => {
    const lines = transcript.split('\n').filter(line => line.trim());
    return lines.map((line, idx) => ({
      id: idx,
      text: line,
      isAgent: line.trim().startsWith('Agent:'),
      isUser: line.trim().startsWith('User:')
    }));
  };

  return (
    <div className="space-y-6">

      {/* Header + Search */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Call Transcripts</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {filteredTranscripts.length} conversation
            {filteredTranscripts.length !== 1 ? "s" : ""}
          </p>
        </div>

        <div className="flex flex-col sm:flex-row gap-3 w-full sm:w-auto">

          {/* Search Bar */}
          <div className="relative">
            <input
              type="text"
              placeholder="Search by phone, call ID or content..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="
                border border-gray-300 dark:border-gray-600 
                rounded-md pl-10 pr-3 py-2 text-sm 
                bg-white dark:bg-gray-700 
                text-gray-900 dark:text-white 
                placeholder-gray-500 dark:placeholder-gray-400 
                focus:outline-none focus:ring-2 focus:ring-blue-500 w-full sm:w-96
              "
            />
            <Search className="h-4 w-4 text-gray-400 dark:text-gray-500 absolute left-3 top-1/2 transform -translate-y-1/2" />
          </div>
        </div>
      </div>

      {/* No Transcripts Found */}
      {filteredTranscripts.length === 0 ? (
        <div className="text-center py-12 bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700">
          <MessageSquare className="mx-auto h-12 w-12 text-gray-400 dark:text-gray-500" />
          <h3 className="mt-2 text-sm font-medium text-gray-900 dark:text-white">No transcripts found</h3>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Try adjusting your search criteria.
          </p>
        </div>
      ) : (
        <div className="space-y-6 max-h-[800px] overflow-y-auto pr-2">

          {filteredTranscripts.map((transcript) => {
            const timestamp = formatTimestamp(transcript.created_at);
            const parsedLines = parseTranscript(transcript.transcript);

            return (
              <div
                key={transcript.call_id}
                className="
                  bg-white dark:bg-gray-800 
                  rounded-lg shadow-sm 
                  border border-gray-200 dark:border-gray-700
                "
              >
                {/* Transcript Header */}
                <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-700">
                  <div className="flex items-center justify-between flex-wrap gap-2">
                    <div className="flex items-center space-x-3">
                      <Phone className="h-5 w-5 text-gray-400 dark:text-gray-500" />
                      <div>
                        <h4 className="text-sm font-medium text-gray-900 dark:text-white">
                          {transcript.phone_number}
                        </h4>
                        <p className="text-xs text-gray-500 dark:text-gray-400">
                          Call ID: {transcript.call_id}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center text-xs text-gray-500 dark:text-gray-400">
                      <Clock className="h-3 w-3 mr-1" />
                      {timestamp.date} {timestamp.time}
                    </div>
                  </div>
                </div>

                {/* Transcript Content */}
                <div className="p-6 max-h-[600px] overflow-y-auto">
                {/* <div className="p-6"> */}
                  <div className="space-y-3">
                    {parsedLines.map((line) => (
                      <div
                        key={line.id}
                        className={`
                          p-3 rounded-lg text-sm
                          ${line.isAgent 
                            ? 'bg-blue-50 dark:bg-blue-900/20 border-l-4 border-blue-500' 
                            : line.isUser 
                            ? 'bg-green-50 dark:bg-green-900/20 border-l-4 border-green-500'
                            : 'bg-gray-50 dark:bg-gray-700/50'
                          }
                        `}
                      >
                        <div className="text-gray-900 dark:text-gray-100 leading-relaxed prose prose-sm max-w-none dark:prose-invert prose-headings:text-gray-900 dark:prose-headings:text-white prose-p:text-gray-900 dark:prose-p:text-gray-100 prose-li:text-gray-900 dark:prose-li:text-gray-100 prose-strong:text-gray-900 dark:prose-strong:text-white">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {line.text}
                          </ReactMarkdown>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            );
          })}

        </div>
      )}
    </div>
  );
}
