"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { fetchAuthStatus, fetchCurrentUser, login, register } from "@/lib/api";
import { getAuthToken, getRecentAuthUsernames } from "@/lib/auth";

type Mode = "login" | "register";

function friendlyAuthError(error: unknown, mode: Mode): string {
  const message = error instanceof Error ? error.message : "请求失败";
  const normalized = message.toLowerCase();
  if (normalized.includes("invalid username or password")) {
    return "账号或密码错误，请重新输入";
  }
  if (normalized.includes("username or email already exists")) {
    return "这个用户名或邮箱已经注册";
  }
  if (normalized.includes("registration disabled")) {
    return "当前未开放新账号注册";
  }
  if (normalized.includes("request failed: 422")) {
    return mode === "login" ? "请输入完整的账号和密码" : "请检查注册信息是否填写正确";
  }
  return message;
}

export default function LoginPage(): JSX.Element {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [firstRun, setFirstRun] = useState(false);
  const [allowRegistration, setAllowRegistration] = useState(false);
  const [checking, setChecking] = useState(true);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [email, setEmail] = useState("");
  const [autoLogin, setAutoLogin] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams(window.location.search);
    const requestedMode: Mode = params.get("mode") === "register" ? "register" : "login";
    const recentUser = getRecentAuthUsernames()[0];
    if (recentUser) {
      setUsername(recentUser);
    }

    void fetchAuthStatus()
      .then(async (status) => {
        if (cancelled) return;
        if (!status.auth_required) {
          router.replace("/");
          return;
        }

        setAllowRegistration(status.allow_registration);
        if (getAuthToken()) {
          try {
            await fetchCurrentUser();
            if (!cancelled) router.replace("/");
            return;
          } catch {
            if (!cancelled) setError("自动登录已过期，请重新登录");
          }
        }

        if (status.user_count === 0 && status.allow_registration) {
          setFirstRun(true);
          setMode("register");
        } else {
          setMode(requestedMode === "register" && status.allow_registration ? "register" : "login");
        }
      })
      .catch(() => {
        if (!cancelled) setError("无法连接 On1y 服务，请稍后重试");
      })
      .finally(() => {
        if (!cancelled) setChecking(false);
      });

    return () => {
      cancelled = true;
    };
  }, [router]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const name = username.trim();
    if (!name || !password) {
      setError("请输入账号和密码");
      return;
    }
    if (mode === "register") {
      if (name.length < 2) {
        setError("用户名至少需要 2 个字符");
        return;
      }
      if (password.length < 8) {
        setError("密码至少需要 8 位");
        return;
      }
      if (password !== confirmPassword) {
        setError("两次输入的密码不一致");
        return;
      }
    }

    setLoading(true);
    try {
      if (mode === "login") {
        await login(name, password, autoLogin);
      } else {
        await register({
          username: name,
          password,
          email: email.trim() || undefined,
          persist: autoLogin
        });
      }
      router.replace("/");
      router.refresh();
    } catch (err) {
      setError(friendlyAuthError(err, mode));
    } finally {
      setLoading(false);
    }
  }

  function switchMode(nextMode: Mode): void {
    setMode(nextMode);
    setError(null);
    setPassword("");
    setConfirmPassword("");
  }

  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f6f6f3] text-sm text-neutral-400">
        正在检查登录状态…
      </div>
    );
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#f6f6f3] px-4 py-10">
      <div className="pointer-events-none absolute -left-28 top-[-8rem] h-80 w-80 rounded-full bg-amber-100/70 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-32 right-[-7rem] h-96 w-96 rounded-full bg-blue-100/70 blur-3xl" />

      <section className="relative w-full max-w-[420px] rounded-[28px] border border-black/[0.07] bg-white/95 p-7 shadow-[0_24px_80px_rgba(0,0,0,0.09)] backdrop-blur sm:p-9">
        <div className="mb-7 text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-neutral-950 shadow-lg shadow-neutral-300">
            <img src="/on1y-logo.png" alt="On1y" width={48} height={48} className="h-12 w-12 object-contain" />
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-neutral-950">On1y 知识库</h1>
          <p className="mt-2 text-sm text-neutral-500">
            {firstRun
              ? "创建第一个账号，开始整理你的知识"
              : mode === "login"
                ? "登录你的个人知识工作台"
                : "创建一个独立的本地账号"}
          </p>
        </div>

        {allowRegistration && !firstRun ? (
          <div className="mb-6 grid grid-cols-2 rounded-xl bg-neutral-100 p-1 text-sm">
            <button
              type="button"
              onClick={() => switchMode("login")}
              className={`rounded-lg py-2 font-medium transition ${mode === "login" ? "bg-white text-neutral-950 shadow-sm" : "text-neutral-500 hover:text-neutral-800"}`}
            >
              登录
            </button>
            <button
              type="button"
              onClick={() => switchMode("register")}
              className={`rounded-lg py-2 font-medium transition ${mode === "register" ? "bg-white text-neutral-950 shadow-sm" : "text-neutral-500 hover:text-neutral-800"}`}
            >
              注册账号
            </button>
          </div>
        ) : null}

        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-neutral-600">账号</span>
            <input
              className="w-full rounded-xl border border-neutral-200 bg-neutral-50/70 px-3.5 py-3 text-sm text-neutral-950 outline-none transition placeholder:text-neutral-400 focus:border-neutral-900 focus:bg-white focus:ring-2 focus:ring-neutral-900/5"
              value={username}
              onChange={(event) => {
                setUsername(event.target.value);
                setError(null);
              }}
              autoComplete="username"
              placeholder="请输入用户名"
              autoFocus
            />
          </label>

          {mode === "register" ? (
            <label className="block">
              <span className="mb-1.5 block text-xs font-medium text-neutral-600">邮箱（可选）</span>
              <input
                type="email"
                className="w-full rounded-xl border border-neutral-200 bg-neutral-50/70 px-3.5 py-3 text-sm text-neutral-950 outline-none transition placeholder:text-neutral-400 focus:border-neutral-900 focus:bg-white focus:ring-2 focus:ring-neutral-900/5"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
                placeholder="you@example.com"
              />
            </label>
          ) : null}

          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-neutral-600">
              密码{mode === "register" ? "（至少 8 位）" : ""}
            </span>
            <div className="relative">
              <input
                type={showPassword ? "text" : "password"}
                className="w-full rounded-xl border border-neutral-200 bg-neutral-50/70 px-3.5 py-3 pr-16 text-sm text-neutral-950 outline-none transition focus:border-neutral-900 focus:bg-white focus:ring-2 focus:ring-neutral-900/5"
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                  setError(null);
                }}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                placeholder="请输入密码"
              />
              <button
                type="button"
                onClick={() => setShowPassword((visible) => !visible)}
                className="absolute inset-y-0 right-3 text-xs font-medium text-neutral-400 hover:text-neutral-800"
                aria-label={showPassword ? "隐藏密码" : "显示密码"}
              >
                {showPassword ? "隐藏" : "显示"}
              </button>
            </div>
          </label>

          {mode === "register" ? (
            <label className="block">
              <span className="mb-1.5 block text-xs font-medium text-neutral-600">确认密码</span>
              <input
                type={showPassword ? "text" : "password"}
                className="w-full rounded-xl border border-neutral-200 bg-neutral-50/70 px-3.5 py-3 text-sm text-neutral-950 outline-none transition focus:border-neutral-900 focus:bg-white focus:ring-2 focus:ring-neutral-900/5"
                value={confirmPassword}
                onChange={(event) => {
                  setConfirmPassword(event.target.value);
                  setError(null);
                }}
                autoComplete="new-password"
                placeholder="再次输入密码"
              />
            </label>
          ) : null}

          <label className="flex cursor-pointer items-center gap-2.5 py-0.5 text-xs text-neutral-600">
            <input
              type="checkbox"
              checked={autoLogin}
              onChange={(event) => setAutoLogin(event.target.checked)}
              className="h-4 w-4 rounded border-neutral-300 accent-neutral-950"
            />
            <span>自动登录 <span className="text-neutral-400">（仅保存加密登录令牌，不保存密码）</span></span>
          </label>

          {error ? (
            <div role="alert" aria-live="polite" className="flex items-start gap-2 rounded-xl border border-red-100 bg-red-50 px-3.5 py-3 text-xs leading-relaxed text-red-700">
              <span className="mt-0.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-red-500" />
              <span>{error}</span>
            </div>
          ) : null}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-xl bg-neutral-950 py-3 text-sm font-medium text-white shadow-sm transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? "请稍候…" : mode === "login" ? "登录" : "注册并登录"}
          </button>
        </form>

        <p className="mt-6 text-center text-[11px] leading-relaxed text-neutral-400">
          账号信息与知识库数据均保存在本机 On1y 服务中
        </p>
      </section>
    </main>
  );
}