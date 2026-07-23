const 允许来源 = "https://linfeisama.github.io";
const 仓库所有者 = "linfeisama";
const 仓库名称 = "a-share-mainline-dashboard";
const 工作流编号 = "318569393";
const 默认分支 = "main";
const GitHub接口 = `https://api.github.com/repos/${仓库所有者}/${仓库名称}`;

function 跨域响应头(origin) {
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Cache-Control": "no-store",
    "Content-Type": "application/json; charset=utf-8",
    "Vary": "Origin",
  };
}

function 返回数据(origin, data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: 跨域响应头(origin),
  });
}

async function 请求GitHub(path, token, options = {}) {
  const headers = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "A-Share-Mainline-Dashboard",
    "X-GitHub-Api-Version": "2026-03-10",
    ...(options.headers || {}),
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  return fetch(`${GitHub接口}${path}`, { ...options, headers });
}

async function 获取工作流任务(token) {
  const response = await 请求GitHub(
    `/actions/workflows/${工作流编号}/runs?event=workflow_dispatch&branch=${默认分支}&per_page=10`,
    token,
  );
  if (!response.ok) {
    throw new Error(`读取更新任务失败（GitHub ${response.status}）`);
  }
  const payload = await response.json();
  return payload.workflow_runs || [];
}

function 精简任务(run) {
  if (!run) return null;
  return {
    run_id: run.id,
    status: run.status,
    conclusion: run.conclusion,
    created_at: run.created_at,
    updated_at: run.updated_at,
  };
}

async function 等待新任务(token, 开始时间) {
  for (let attempt = 0; attempt < 6; attempt += 1) {
    const runs = await 获取工作流任务(token);
    const run = runs.find((item) => Date.parse(item.created_at) >= 开始时间 - 5000);
    if (run) return run;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return null;
}

async function 触发更新(request, env, origin) {
  if (!env.GITHUB_TOKEN) {
    return 返回数据(origin, { ok: false, message: "云端更新密钥尚未配置" }, 503);
  }

  const limit = await env.UPDATE_RATE_LIMITER.limit({ key: "dashboard-refresh" });
  if (!limit.success) {
    return 返回数据(origin, { ok: false, message: "请求过于频繁，请稍后再试" }, 429);
  }

  const runs = await 获取工作流任务(env.GITHUB_TOKEN);
  const activeRun = runs.find((run) => ["queued", "in_progress", "waiting", "pending"].includes(run.status));
  if (activeRun) {
    return 返回数据(origin, {
      ok: true,
      reused: true,
      message: "已有更新任务正在运行",
      run: 精简任务(activeRun),
    });
  }

  const latestRun = runs[0];
  if (latestRun && Date.now() - Date.parse(latestRun.created_at) < 120000) {
    return 返回数据(origin, {
      ok: true,
      reused: true,
      message: "最近一次更新刚刚完成",
      run: 精简任务(latestRun),
    });
  }

  const 开始时间 = Date.now();
  const response = await 请求GitHub(
    `/actions/workflows/${工作流编号}/dispatches`,
    env.GITHUB_TOKEN,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ref: 默认分支 }),
    },
  );
  if (!response.ok) {
    const detail = await response.text();
    console.error("触发 GitHub Actions 失败", response.status, detail);
    return 返回数据(origin, { ok: false, message: `触发更新失败（GitHub ${response.status}）` }, 502);
  }

  let run = null;
  if (response.status !== 204) {
    const payload = await response.json().catch(() => ({}));
    if (payload.workflow_run_id) {
      run = {
        id: payload.workflow_run_id,
        status: "queued",
        conclusion: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
    }
  }
  run ||= await 等待新任务(env.GITHUB_TOKEN, 开始时间);
  return 返回数据(origin, {
    ok: true,
    reused: false,
    message: "更新任务已提交",
    run: 精简任务(run),
  });
}

async function 查询状态(request, env, origin) {
  const url = new URL(request.url);
  const runId = url.searchParams.get("run_id");
  let run = null;
  if (runId && /^\d+$/.test(runId)) {
    const response = await 请求GitHub(`/actions/runs/${runId}`, env.GITHUB_TOKEN);
    if (response.status === 404) {
      return 返回数据(origin, { ok: false, message: "没有找到对应的更新任务" }, 404);
    }
    if (!response.ok) {
      return 返回数据(origin, { ok: false, message: `查询更新状态失败（GitHub ${response.status}）` }, 502);
    }
    run = await response.json();
  } else {
    const runs = await 获取工作流任务(env.GITHUB_TOKEN);
    run = runs[0] || null;
  }
  return 返回数据(origin, {
    ok: true,
    message: run ? "已获取更新状态" : "暂未发现更新任务",
    run: 精简任务(run),
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = decodeURIComponent(url.pathname);
    const origin = request.headers.get("Origin") || "";
    if (origin !== 允许来源) {
      return 返回数据(允许来源, { ok: false, message: "不允许从当前页面调用更新接口" }, 403);
    }
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: 跨域响应头(origin) });
    }

    try {
      if (request.method === "POST" && path === "/更新行情") {
        return await 触发更新(request, env, origin);
      }
      if (request.method === "GET" && path === "/更新状态") {
        return await 查询状态(request, env, origin);
      }
      return 返回数据(origin, { ok: false, message: "接口路径不存在" }, 404);
    } catch (error) {
      console.error(error);
      return 返回数据(origin, { ok: false, message: error.message || "云端更新接口异常" }, 500);
    }
  },
};
