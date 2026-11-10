import { useState } from "react";

interface LoginProps {
  onLogin: (username: string) => void;
}

export default function Login({ onLogin }: LoginProps) {
  const [username, setUsername] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (username.trim()) onLogin(username.trim());
  }

  return (
    <form className="panel" onSubmit={handleSubmit}>
      <h1>Adaptive Interview Agent</h1>
      <label>
        Username
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="e.g. jane_doe"
          required
          autoFocus
        />
      </label>
      <button type="submit">Continue</button>
    </form>
  );
}
