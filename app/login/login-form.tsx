"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff } from "lucide-react";
import { loginAction } from "@/app/actions/auth";

export default function LoginForm({ destino }: { destino: string }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [mostrarSenha, setMostrarSenha] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [pendente, iniciar] = useTransition();

  function enviar(e: React.FormEvent) {
    e.preventDefault();
    setErro(null);
    iniciar(async () => {
      const r = await loginAction(email, senha);
      if (r.ok) {
        router.replace(destino);
        router.refresh();
      } else {
        setSenha("");
        setErro(r.erro);
      }
    });
  }

  const campo =
    "w-full bg-panel2 border border-line rounded-xl px-3 py-2.5 text-sm text-ink placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-frost/40";

  return (
    <form onSubmit={enviar} className="flex flex-col gap-4">
      <label className="flex flex-col gap-1.5">
        <span className="text-xs font-medium text-muted">E-mail</span>
        <input
          type="email"
          autoComplete="username"
          required
          maxLength={254}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={campo}
          placeholder="voce@empresa.com"
        />
      </label>

      <label className="flex flex-col gap-1.5">
        <span className="text-xs font-medium text-muted">Senha</span>
        <div className="relative">
          <input
            type={mostrarSenha ? "text" : "password"}
            autoComplete="current-password"
            required
            maxLength={128}
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            className={`${campo} pr-10`}
          />
          <button
            type="button"
            onClick={() => setMostrarSenha((v) => !v)}
            aria-label={mostrarSenha ? "Ocultar senha" : "Mostrar senha"}
            aria-pressed={mostrarSenha}
            title={mostrarSenha ? "Ocultar senha" : "Mostrar senha"}
            className="absolute inset-y-0 right-0 flex items-center px-3 text-muted hover:text-ink"
          >
            {mostrarSenha ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        </div>
      </label>

      {erro && (
        <p role="alert" className="text-sm text-red-500">
          {erro}
        </p>
      )}

      <button
        type="submit"
        disabled={pendente}
        className="w-full rounded-xl bg-frost text-white py-2.5 text-sm font-medium hover:bg-frostdark transition-colors disabled:opacity-60"
      >
        {pendente ? "Entrando..." : "Entrar"}
      </button>
    </form>
  );
}
