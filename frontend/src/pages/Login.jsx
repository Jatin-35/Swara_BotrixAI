import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import ThemeToggle from "../components/ThemeToggle";
import { Lock } from "lucide-react";

export default function Login() {
  const [username, setUser] = useState("");
  const [password, setPass] = useState("");
  const navigate = useNavigate();

  // Auto redirect if already logged in
  useEffect(() => {
    if (localStorage.getItem("auth") === "true") {
      navigate("/dashboard", { replace: true });
    }
  }, [navigate]);

  function handleLogin(e) {
    e.preventDefault();

    if (username === "admin" && password === "admin123") {
      localStorage.setItem("auth", "true");
      navigate("/dashboard", { replace: true });
    } else {
      alert("Invalid login");
    }
  }

  return (
    <div className="min-h-screen flex flex-col justify-center items-center 
      bg-gradient-to-br from-gray-100 to-gray-200 
      dark:from-gray-900 dark:to-gray-800 transition-colors relative">

      {/* THEME TOGGLE */}
      <div className="absolute top-4 right-4">
        <ThemeToggle />
      </div>

      {/* LOGO */}
      <div className="flex flex-col items-center mb-4">
        <img 
          src="/header_logo.png"
          alt="App Logo" 
          className="h-16 w-auto object-contain drop-shadow-lg"
        />
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white mt-3">
          Swara The Fashion Street
        </h1>
        <p className="text-gray-600 dark:text-gray-400 mt-1">
          Sign in to continue
        </p>
      </div>

      {/* LOGIN CARD */}
      <form
        onSubmit={handleLogin}
        className="
          w-full max-w-md 
          backdrop-blur-lg 
          bg-white/70 dark:bg-gray-800/70 
          border border-gray-200 dark:border-gray-700 
          shadow-2xl rounded-2xl p-8 
          transition-all duration-300
        "
      >
        <div className="flex items-center justify-center mb-6">
          <Lock className="h-6 w-6 text-gray-400 dark:text-gray-500 mr-2" />
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
            Login
          </h2>
        </div>

        {/* INPUTS */}
        <div className="space-y-4">
          
          {/* USERNAME */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Username
            </label>
            <input
              className="
                w-full px-3 py-2 rounded-md
                bg-white dark:bg-gray-700 
                border border-gray-300 dark:border-gray-600
                text-gray-900 dark:text-white 
                placeholder-gray-500 dark:placeholder-gray-400
                focus:outline-none focus:ring-2 focus:ring-blue-500
              "
              placeholder="Enter your username"
              value={username}
              onChange={(e) => setUser(e.target.value)}
              required
            />
          </div>

          {/* PASSWORD */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Password
            </label>
            <input
              className="
                w-full px-3 py-2 rounded-md
                bg-white dark:bg-gray-700 
                border border-gray-300 dark:border-gray-600
                text-gray-900 dark:text-white 
                placeholder-gray-500 dark:placeholder-gray-400
                focus:outline-none focus:ring-2 focus:ring-blue-500
              "
              placeholder="Enter your password"
              type="password"
              value={password}
              onChange={(e) => setPass(e.target.value)}
              required
            />
          </div>
        </div>

        {/* SUBMIT BUTTON */}
        <button
          type="submit"
          className="
            w-full mt-6 px-4 py-2 
            bg-blue-600 hover:bg-blue-700 
            dark:bg-blue-500 dark:hover:bg-blue-600 
            text-white font-medium rounded-md 
            transition-all shadow-md hover:shadow-lg
            focus:outline-none focus:ring-2 focus:ring-blue-500
          "
        >
          Sign In
        </button>

        {/* DEMO CREDENTIALS */}
        <div className="mt-4 text-center">
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Demo credentials: <span className="font-semibold">admin / admin123</span>
          </p>
        </div>
      </form>
    </div>
  );
}
