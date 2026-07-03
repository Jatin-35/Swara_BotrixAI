import { RefreshCw } from "lucide-react";

export default function LoadingSpinner({ message = "Loading..." }) {
  return (
    <div className="flex flex-col items-center justify-center py-12">
      <RefreshCw className="h-8 w-8 animate-spin text-blue-600 dark:text-blue-400 mb-4" />
      <p className="text-lg text-gray-600 dark:text-gray-300">{message}</p>
    </div>
  );
}
