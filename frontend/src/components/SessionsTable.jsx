import { useState } from "react";
import { getRecordingUrl, downloadRecording } from "../utils/api";
import { Phone, Clock, CheckCircle, XCircle, Play, Download, Calendar, X } from "lucide-react";

export default function SessionsTable({ sessions }) {
  const [showModal, setShowModal] = useState(false);
  const [currentRecording, setCurrentRecording] = useState(null);
  const [currentSession, setCurrentSession] = useState(null);

  const formatDuration = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
  };

  const formatDateTime = (dateString) => {
    const date = new Date(dateString);
    return {
      date: date.toLocaleDateString(),
      time: date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };
  };

  const getStatusBadge = (status) => {
    const base =
      "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium";

    switch (status) {
      case "completed":
        return `${base} bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300`;
      case "abandoned":
        return `${base} bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300`;
      case "failed":
        return `${base} bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300`;
      default:
        return `${base} bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300`;
    }
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case "completed":
        return <CheckCircle className="h-4 w-4 text-green-500 dark:text-green-400" />;
      case "abandoned":
      case "failed":
        return <XCircle className="h-4 w-4 text-red-500 dark:text-red-400" />;
      default:
        return <Clock className="h-4 w-4 text-yellow-500 dark:text-yellow-400" />;
    }
  };

  const openRecordingModal = (url, session) => {
    setCurrentRecording(url);
    setCurrentSession(session);
    setShowModal(true);
  };

  const closeModal = () => {
    setShowModal(false);
    setCurrentRecording(null);
    setCurrentSession(null);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
          Call Sessions
        </h3>
        <div className="text-sm text-gray-500 dark:text-gray-400">
          {sessions.length} session{sessions.length !== 1 ? "s" : ""}
        </div>
      </div>

      <div className="bg-white dark:bg-gray-900 shadow-sm rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700 max-h-[800px] overflow-y-auto">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-800">
              <tr>
                {["Session Details", "Contact", "Firm", "Vertical", "Rating", "Status", "Recording"].map(
                  (header) => (
                    <th
                      key={header}
                      className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider"
                    >
                      {header}
                    </th>
                  )
                )}
              </tr>
            </thead>

            <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
              {sessions.map((session, i) => {
                const url = getRecordingUrl(session.recording_url);
                const startTime = formatDateTime(session.started_at);
                const endTime = formatDateTime(session.ended_at);

                return (
                  <tr
                    key={i}
                    className="hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                  >
                    {/* SESSION DETAILS */}
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center">
                        <Phone className="h-5 w-5 text-gray-400 dark:text-gray-500" />
                        <div className="ml-3">
                          <div className="text-sm font-medium text-gray-900 dark:text-white">
                            {session.session_id.substring(0, 20)}...
                          </div>
                          <div className="text-sm text-gray-500 dark:text-gray-400 flex items-center">
                            <Calendar className="h-3 w-3 mr-1" />
                            {startTime.date} {startTime.time}
                          </div>
                        </div>
                      </div>
                    </td>

                    {/* CONTACT */}
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="text-sm text-gray-900 dark:text-white">
                        {session.phone_number}
                      </div>
                      <div className="text-sm text-gray-500 dark:text-gray-400">
                        {session.caller_name || "Unknown Caller"}
                      </div>
                    </td>

                    {/* FIRM */}
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                      {session.firm_name || "--"}
                    </td>

                    {/* VERTICAL */}
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300">
                        {session.business_vertical || "General"}
                      </span>
                    </td>

                    {/* RATING */}
                    <td className="px-6 py-4 whitespace-nowrap">
                      {session.rating ? (
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium 
                            ${session.rating === 'Hot' ? 'bg-red-100 text-red-800' :
                            session.rating === 'Warm' ? 'bg-orange-100 text-orange-800' :
                              'bg-gray-100 text-gray-800'}`}>
                          {session.rating}
                        </span>
                      ) : (
                        <span className="text-gray-400 text-xs">--</span>
                      )}
                    </td>

                    {/* STATUS */}
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center space-x-2">
                        {getStatusIcon(session.status)}
                        <span className={getStatusBadge(session.status)}>
                          {session.status}
                        </span>
                      </div>
                    </td>

                    {/* DURATION */}
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center text-sm text-gray-900 dark:text-white">
                        <Clock className="h-4 w-4 mr-1 text-gray-400 dark:text-gray-500" />
                        {formatDuration(session.duration_seconds)}
                      </div>
                      <div className="text-xs text-gray-500 dark:text-gray-400">
                        Ended: {endTime.time}
                      </div>
                    </td>

                    {/* RECORDING */}
                    <td className="px-6 py-4 whitespace-nowrap">
                      {url ? (
                        <div className="flex space-x-2">

                          {/* VIEW BUTTON */}
                          <button
                            onClick={() => openRecordingModal(url, session)}
                            className="
                              inline-flex items-center px-3 py-1 rounded-md text-xs font-medium
                              text-blue-700 bg-blue-100 hover:bg-blue-200
                              dark:text-blue-300 dark:bg-blue-900/40 dark:hover:bg-blue-900/60
                              transition-colors
                            "
                          >
                            <Play className="h-3 w-3 mr-1" />
                            View
                          </button>

                          {/* DOWNLOAD BUTTON */}
                          <button
                            onClick={() => downloadRecording(url)}
                            className="
                              inline-flex items-center px-3 py-1 rounded-md text-xs font-medium
                              text-green-700 bg-green-100 hover:bg-green-200
                              dark:text-green-300 dark:bg-green-900/40 dark:hover:bg-green-900/60
                              transition-colors
                            "
                          >
                            <Download className="h-3 w-3 mr-1" />
                            Download
                          </button>
                        </div>
                      ) : (
                        <span
                          className="
                            inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium 
                            bg-gray-100 text-gray-800 
                            dark:bg-gray-700 dark:text-gray-300
                          "
                        >
                          No recording
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>

          </table>
        </div>
      </div>

      {/* RECORDING MODAL */}
      {showModal && currentRecording && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-75 p-4"
          onClick={closeModal}
        >
          <div
            className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl max-w-4xl w-full max-h-[90vh] overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* HEADER */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Call Recording
                </h3>
                <div className="mt-1 space-y-1">
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    Session: {currentSession?.session_id?.substring(0, 30)}...
                  </p>
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    Contact: {currentSession?.phone_number}
                  </p>
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    Duration: {formatDuration(currentSession?.duration_seconds || 0)}
                  </p>
                </div>
              </div>
              <button
                onClick={closeModal}
                className="p-2 rounded-md text-gray-500 hover:text-gray-700 hover:bg-gray-100 dark:text-gray-400 dark:hover:text-gray-200 dark:hover:bg-gray-700 transition-colors"
                aria-label="Close modal"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* VIDEO PLAYER */}
            <div className="p-6 bg-black">
              <video
                src={currentRecording}
                controls
                autoPlay
                controlsList="nodownload"
                className="w-full max-h-[70vh] rounded-lg"
              >
                Your browser does not support the video tag.
              </video>
            </div>

            {/* FOOTER */}
            <div className="px-6 py-4 bg-gray-50 dark:bg-gray-900 border-t border-gray-200 dark:border-gray-700">
              <div className="flex items-center justify-between">
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  Use video controls to play, pause, adjust volume, or go fullscreen.
                </p>
                <div className="flex space-x-3">
                  <button
                    onClick={() => downloadRecording(currentRecording)}
                    className="
                      inline-flex items-center px-4 py-2 rounded-md text-sm font-medium
                      text-white bg-blue-600 hover:bg-blue-700
                      dark:bg-blue-500 dark:hover:bg-blue-600
                      transition-colors
                    "
                  >
                    <Download className="h-4 w-4 mr-2" />
                    Download
                  </button>
                  <button
                    onClick={closeModal}
                    className="
                      inline-flex items-center px-4 py-2 rounded-md text-sm font-medium
                      text-gray-700 bg-white hover:bg-gray-50
                      dark:text-gray-200 dark:bg-gray-700 dark:hover:bg-gray-600
                      border border-gray-300 dark:border-gray-600
                      transition-colors
                    "
                  >
                    Close
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
