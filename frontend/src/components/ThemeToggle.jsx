import { useContext } from 'react';
import { Sun, Moon } from 'lucide-react';
import { ThemeContext } from '../context/ThemeContext';

export default function ThemeToggle() {
  const { theme, toggle } = useContext(ThemeContext);

  return (
    <button
      onClick={toggle}
      className="p-2 rounded-md text-gray-500 hover:text-gray-700 hover:bg-gray-100 dark:text-gray-400 dark:hover:text-gray-200 dark:hover:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
      aria-label="Toggle theme"
    >
      {theme === 'light' ? (
        <Moon className="h-5 w-5" />
      ) : (
        <Sun className="h-5 w-5" />
      )}
    </button>
  );
}