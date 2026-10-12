"use server";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE } from "@/lib/session";

export type LoginResultado = { ok: true } | { ok: false; erro: string };

export async function loginAction(email: string, senha: string): Promise<LoginResultado> {
  const base = (process.env.API_URL ?? "").replace(/\/$/, "");
  if (!base) return { ok: false, erro: "API_URL não está configurada no servidor." };
  if (!email.trim() || !senha) return { ok: false, erro: "Informe e-mail e senha." };

  // A API enxerga só o IP deste servidor. Para o limite de tentativas por IP
  // funcionar, repassamos o IP real do navegador, junto com um segredo que só
  // este servidor conhece (PROXY_SHARED_SECRET, sem NEXT_PUBLIC_).
  const cabecalhos: Record<string, string> = { "Content-Type": "application/json" };
  const segredo = process.env.PROXY_SHARED_SECRET ?? "";
  if (segredo) {
    const h = headers();
    const ip = (h.get("x-forwarded-for") ?? h.get("x-real-ip") ?? "").split(",")[0].trim();
    cabecalhos["X-Proxy-Secret"] = segredo;
    if (ip) cabecalhos["X-Client-IP"] = ip;
  }

  let res: Response;
  try {
    res = await fetch(`${base}/api/auth/login`, {
      method: "POST",
      headers: cabecalhos,
      body: JSON.stringify({ email: email.trim(), senha }),
      cache: "no-store",
      signal: AbortSignal.timeout(20_000),
    });
  } catch {
    return { ok: false, erro: "Não consegui falar com a API. Tente de novo em instantes." };
  }

  if (res.status === 429) {
    return { ok: false, erro: "Muitas tentativas. Aguarde alguns minutos e tente de novo." };
  }
  if (res.status === 401) {
    return { ok: false, erro: "E-mail ou senha inválidos, ou conta temporariamente bloqueada." };
  }
  if (!res.ok) return { ok: false, erro: "Erro ao entrar. Tente de novo em instantes." };

  const dados = (await res.json()) as { access_token: string; expires_in: number };
  cookies().set(SESSION_COOKIE, dados.access_token, {
    httpOnly: true, // JavaScript da página não consegue ler (protege contra XSS)
    secure: process.env.NODE_ENV === "production", // só trafega por HTTPS
    sameSite: "lax", // não vai em POSTs vindos de outros sites (protege contra CSRF)
    path: "/",
    maxAge: dados.expires_in,
  });
  return { ok: true };
}

export async function logoutAction() {
  cookies().delete(SESSION_COOKIE);
  redirect("/login");
}
