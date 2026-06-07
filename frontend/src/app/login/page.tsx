"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { fetchAuthStatus, login, register } from "@/lib/api";

export default function LoginPage(): JSX.Element {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [firstRun, setFirstRun] = useState(false);
  const [checking, setChecking] = useState(true);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("mode") === "register") {
      setMode("register");
    }
    void fetchAuthStatus()
      .then((status) => {
        if (!status.auth_required) {
          router.replace("/");
          return;
        }
        if (status.user_count === 0 && status.allow_registration) {
          setFirstRun(true);
          setMode("register");
        }
      })
      .finally(() => {
        setChecking(false);
      });
  }, [router]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      if (mode === "login") {
        await login(username.trim(), password);
      } else {
        await register({
          username: username.trim(),
          password,
          email: email.trim() || undefined
        });
      }
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "请求失败");
    } finally {
      setLoading(false);
    }
  }

  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-neutral-50 text-sm text-neutral-400">
        正在加载…
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-50 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <img
            src="/on1y-logo.png"
            alt="On1y"
            width={56}
            height={56}
            className="mx-auto mb-3 h-14 w-14 object-contain"
          />
          <h1 className="text-xl font-semibold tracking-tight text-neutral-900">On1y 知识库</h1>
          <p className="mt-1 text-sm text-neutral-500">
            {firstRun
              ? "欢迎使用 On1y，先创建你的第一个账号"
              : mode === "login"
                ? "登录你的个人知识工作台"
                : "创建一个新账号"}
          </p>
        </div>

        <form
          onSubmit={onSubmit}
          className="space-y-4 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm"
        >
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-neutral-600">用户名</span>
            <input
              className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-900 outline-none transition focus:border-neutral-900"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              placeholder="admin"
              required
            />
          </label>

          {mode === "register" ? (
            <label className="block">
              <span className="mb-1.5 block text-xs font-medium text-neutral-600">邮箱（可选）</span>
              <input
                type="email"
                className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-900 outline-none transition focus:border-neutral-900"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                placeholder="you@example.com"
              />
            </label>
          ) : null}

          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-neutral-600">
              密码{mode === "register" ? "（至少 8 位）" : ""}
            </span>
            <input
              type="password"
              className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-900 outline-none transition focus:border-neutral-900"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
              minLength={mode === "register" ? 8 : 1}
            />
          </label>

          {error ? (
            <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">{error}</p>
          ) : null}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-black py-2.5 text-sm font-medium text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? "请稍候…" : mode === "login" ? "登录" : "注册并登录"}
          </button>

          {firstRun ? null : (
            <button
              type="button"
              className="w-full text-center text-xs text-neutral-500 transition hover:text-neutral-900"
              onClick={() => {
                setError(null);
                setMode(mode === "login" ? "register" : "login");
              }}
            >
              {mode === "login" ? "没有账号？注册一个" : "已有账号？返回登录"}
            </button>
          )}
        </form>

        <p className="mt-6 text-center text-[11px] leading-relaxed text-neutral-400">
          数据仅保存在你本地的 On1y 服务中
        </p>
      </div>
    </div>
  );
}
