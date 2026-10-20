import React, { useEffect, useRef, useState } from 'react';
import {
  CloudRain,
  Coins,
  Route,
  Footprints,
  Plus,
  Trash2,
  Download,
  ArrowRight,
} from 'lucide-react';
import { api } from '../../lib/api';
import { useApp } from '../../context/AppContext';
import { PageShell } from '../ui/PageShell';
import { RiskExplanationChain } from '../risk/RiskExplanationChain';
import { RiskOptimizationLoop } from '../risk/RiskOptimizationLoop';
import type {
  RiskDay,
  RiskInput,
  RiskLevel,
  RiskOptimizationResult,
  RiskReport,
  RiskWeather,
} from '../../types/risk';
import type { TripRunResponse } from '../../types/api';

const dimensions = [
  { key: 'weather', label: '天气', icon: CloudRain, description: '户外安排会不会受影响' },
  { key: 'budget', label: '预算', icon: Coins, description: '整趟花费有没有余量' },
  { key: 'transport', label: '交通', icon: Route, description: '路线和衔接能不能成立' },
  { key: 'fatigue', label: '体力', icon: Footprints, description: '每天的强度能否接受' },
] as const;
const levels: Record<RiskLevel, { label: string; className: string }> = {
  high: { label: '高风险', className: 'bg-red-50 text-red-800 border-red-200' },
  medium: { label: '需调整', className: 'bg-amber-50 text-amber-900 border-amber-200' },
  low: { label: '较低风险', className: 'bg-emerald-50 text-emerald-900 border-emerald-200' },
  unknown: { label: '待核实', className: 'bg-stone-100 text-stone-700 border-stone-300' },
};
const inputClass =
  'min-h-11 w-full border-b border-stroke bg-transparent px-1 py-2 text-[15px] text-ink outline-none focus:border-accent disabled:opacity-50';
const buttonClass =
  'inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-stroke px-4 py-2 text-sm font-medium text-ink hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-50';
const blankWeather = (): RiskWeather => ({
  data_kind: 'unavailable',
  observed_at: null,
  source_label: '手动录入，未经外部核验',
});
const dateOffset = (date: string, days: number) =>
  new Date(new Date(`${date}T12:00:00+08:00`).getTime() + days * 86400000)
    .toISOString()
    .slice(0, 10);
const today = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());
const blankDay = (date: string): RiskDay => ({
  day_id: crypto.randomUUID(),
  date,
  destination: '',
  outdoor_minutes: 180,
  active_minutes: null,
  walking_km: null,
  rest_minutes: null,
  weather: blankWeather(),
  transport_complete: false,
  transports: [],
  connections: [],
});
const blankInput = (): RiskInput => ({
  title: '我的旅行方案',
  is_example: false,
  budget_cap_cny: null,
  costs_complete: false,
  costs: [],
  days: [blankDay(dateOffset(today(), 1))],
  limits: { max_daily_walking_km: 8, max_daily_active_hours: 8, min_daily_rest_minutes: 45 },
});
const fillImportedDefaults = (trip: RiskInput, limits: RiskInput['limits']): RiskInput => ({
  ...trip,
  limits,
  // Imported values stay exactly as imported.  Never turn a traveler limit or
  // an unverified route into a measured day value; missing fields remain null.
});
const numberValue = (value: string) => (value === '' ? null : Number(value));
const weatherTime = (value: string | null) =>
  value
    ? new Date(value)
        .toLocaleString('sv-SE', { timeZone: 'Asia/Shanghai' })
        .slice(0, 16)
        .replace(' ', 'T')
    : '';

const Field: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <label className="block min-w-0">
    <span className="block text-[13px] text-ink-secondary">{label}</span>
    {children}
  </label>
);
const NumberField: React.FC<{
  label: string;
  value: number | null | undefined;
  onChange: (value: number | null) => void;
  min?: number;
  max?: number;
  required?: boolean;
}> = ({ label, value, onChange, min = 0, max, required }) => (
  <Field label={label}>
    <input
      className={inputClass}
      type="number"
      step="any"
      min={min}
      max={max}
      required={required}
      value={value ?? ''}
      placeholder="未知"
      onChange={(e) => onChange(numberValue(e.target.value))}
    />
  </Field>
);
const Badge: React.FC<{ level: RiskLevel }> = ({ level }) => (
  <span
    className={`inline-block rounded-full border px-2.5 py-1 text-xs font-medium ${levels[level].className}`}
  >
    {levels[level].label}
  </span>
);

export const RiskAssessmentPage: React.FC = () => {
  const { state } = useApp();
  const [input, setInput] = useState<RiskInput>(blankInput);
  const [report, setReport] = useState<RiskReport | null>(null);
  const [inputSource, setInputSource] = useState<{
    inputOrigin: 'manual' | 'journeypilot';
    bundleId?: string | null;
  }>({ inputOrigin: 'manual' });
  const [optimization, setOptimization] = useState<RiskOptimizationResult | null>(null);
  const [optimizationApplied, setOptimizationApplied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [runError, setRunError] = useState('');
  const [runs, setRuns] = useState<TripRunResponse[]>([]);
  const [selectedRun, setSelectedRun] = useState(state.currentTripRunId ?? '');
  const revision = useRef(0);
  const resultRef = useRef<HTMLElement>(null);

  useEffect(() => {
    let active = true;
    api
      .listTripRuns({ mode: 'deep', limit: 80 })
      .then((result) => {
        if (active) setRuns(result.runs);
      })
      .catch(() => {
        if (active) setRunError('暂时无法读取已有行程，仍可手动填写。');
      });
    return () => {
      active = false;
      revision.current++;
    };
  }, []);

  const update = (next: RiskInput) => {
    revision.current++;
    setInput(next);
    setReport(null);
    setOptimization(null);
    setOptimizationApplied(false);
    setError('');
  };
  const updateDay = (index: number, patch: Partial<RiskDay>) => {
    const day = input.days[index];
    const changesLocation =
      (patch.date !== undefined && patch.date !== day.date) ||
      (patch.destination !== undefined && patch.destination !== day.destination);
    update({
      ...input,
      days: input.days.map((d, i) =>
        i === index
          ? {
              ...d,
              ...patch,
              ...(changesLocation
                ? {
                    weather: blankWeather(),
                    transport_complete: false,
                    transports: [],
                    connections: [],
                  }
                : {}),
            }
          : d
      ),
    });
  };
  const updateWeather = (index: number, patch: Partial<RiskWeather>) =>
    updateDay(index, {
      weather: {
        ...input.days[index].weather,
        ...patch,
        source_label: '手动录入，未经外部核验',
        source_ids: [],
      },
    });
  const load = async (kind: 'example' | 'trip') => {
    const token = ++revision.current;
    setBusy(true);
    setError('');
    setReport(null);
    setOptimization(null);
    setOptimizationApplied(false);
    try {
      if (kind === 'example') {
        const example = await api.getRiskExample();
        if (revision.current === token) {
          setInput(example);
          setInputSource({ inputOrigin: 'manual' });
        }
      } else {
        const review = await api.getTripRisk(selectedRun);
        if (revision.current === token) {
          const importedInput = fillImportedDefaults(review.input, input.limits);
          const assessment = await api.assessTravelRisk(importedInput, {
            inputOrigin: 'journeypilot',
            bundleId: review.assessment.bundle_id,
          });
          if (revision.current === token) {
            setInput(importedInput);
            setInputSource({
              inputOrigin: 'journeypilot',
              bundleId: review.assessment.bundle_id,
            });
            setReport(assessment);
          }
        }
      }
    } catch (e) {
      if (revision.current === token)
        setError(e instanceof Error ? e.message : '读取失败，请重试。');
    } finally {
      setBusy(false);
    }
  };
  const assess = async (event: React.FormEvent) => {
    event.preventDefault();
    const token = ++revision.current;
    setBusy(true);
    setError('');
    setReport(null);
    setOptimization(null);
    setOptimizationApplied(false);
    try {
      const result = await api.assessTravelRisk(input, inputSource);
      if (revision.current === token) {
        setReport(result);
        requestAnimationFrame(() =>
          resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
        );
      }
    } catch (e) {
      if (revision.current === token)
        setError(e instanceof Error ? e.message : '评估失败，请检查输入后重试。');
    } finally {
      setBusy(false);
    }
  };
  const optimize = async () => {
    if (!report) return;
    const token = ++revision.current;
    setBusy(true);
    setError('');
    setOptimizationApplied(false);
    try {
      const result = await api.optimizeTravelRisk(input, {
        inputOrigin: report.input_origin,
        bundleId: report.bundle_id,
      });
      if (revision.current === token) setOptimization(result);
    } catch (e) {
      if (revision.current === token)
        setError(e instanceof Error ? e.message : '生成优化草稿失败，请重试。');
    } finally {
      setBusy(false);
    }
  };
  const applyOptimization = (nextInput: RiskInput, nextReport: RiskReport) => {
    revision.current++;
    setInput(nextInput);
    setInputSource({ inputOrigin: nextReport.input_origin, bundleId: nextReport.bundle_id });
    setReport(nextReport);
    setOptimizationApplied(true);
    setError('');
    requestAnimationFrame(() =>
      resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    );
  };
  const exportReport = () => {
    if (!report) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify({ input, assessment: report, optimization }, null, 2)], {
        type: 'application/json',
      })
    );
    const link = document.createElement('a');
    link.href = url;
    link.download = '旅行风险评估.json';
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <PageShell
      title="风险评估"
      purpose="这个旅行方案，靠谱吗？先看天气、预算、交通、体力。"
      state={{ kind: 'ready' }}
    >
      <div className="space-y-8 p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-lg text-sm leading-relaxed text-ink-secondary">
            把已有方案放进来，找到需要调整的具体环节。缺失数据会保留为「待核实」。
          </p>
          <button className={buttonClass} disabled={busy} onClick={() => void load('example')}>
            载入云南 5 日示例
          </button>
        </div>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="四项风险概览">
          {dimensions.map(({ key, label, icon: Icon, description }) => {
            const result = report?.dimensions.find((d) => d.category === key);
            return (
              <div key={key} className="border border-stroke p-4">
                <div className="mb-3 flex items-center gap-2">
                  <Icon size={18} />
                  <h2 className="font-semibold text-ink">{label}</h2>
                </div>
                {result ? (
                  <Badge level={result.level} />
                ) : (
                  <span className="text-sm text-ink-muted">等待评估</span>
                )}
                <p className="mt-3 text-xs leading-relaxed text-ink-secondary">
                  {result?.summary ?? description}
                </p>
              </div>
            );
          })}
        </div>
        {input.is_example && (
          <div
            role="note"
            className="border-l-4 border-amber-500 bg-amber-50 p-4 text-sm text-amber-950"
          >
            当前为演示方案：天气、路线和费用均为虚构测试数据，不代表云南实际情况。修改后仍保留演示标记；用「新建手动方案」开始自己的评估。
          </div>
        )}
        <section className="space-y-3 border-y border-stroke py-5" aria-label="导入已有行程">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-0 flex-1">
              <Field label="导入 JourneyPilot 已有行程">
                <select
                  className={inputClass}
                  value={selectedRun}
                  disabled={busy}
                  onChange={(e) => setSelectedRun(e.target.value)}
                >
                  <option value="">选择行程</option>
                  {state.currentTripRunId &&
                    !runs.some((r) => r.run_id === state.currentTripRunId) && (
                      <option value={state.currentTripRunId}>当前行程</option>
                    )}
                  {runs.map((run) => (
                    <option value={run.run_id} key={run.run_id}>
                      {run.title ?? '未命名行程'}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <button
              className={buttonClass}
              disabled={busy || !selectedRun}
              onClick={() => void load('trip')}
            >
              导入并评估
            </button>
            <button className={buttonClass} disabled={busy} onClick={() => {
              update(blankInput());
              setInputSource({ inputOrigin: 'manual' });
            }}>
              新建手动方案
            </button>
          </div>
          <p className="text-xs text-ink-muted">
            旧版页面保留用于兼容手动录入。导入值不会用每日强度上限补齐，缺失数据保持未知；交通是否核对由导入来源决定。
          </p>
          {runError && <p className="text-sm text-ink-secondary">{runError}</p>}
        </section>
        <form onSubmit={assess}>
          <fieldset disabled={busy} className="min-w-0 space-y-7">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="方案名称">
                <input
                  className={inputClass}
                  maxLength={200}
                  required
                  value={input.title}
                  onChange={(e) => update({ ...input, title: e.target.value })}
                />
              </Field>
              <NumberField
                label="全部同行人 · 整趟预算上限（元）"
                value={input.budget_cap_cny}
                min={0.01}
                max={1e10}
                onChange={(budget_cap_cny) => update({ ...input, budget_cap_cny })}
              />
            </div>
            <section aria-label="体力偏好">
              <h2 className="mb-4 text-lg font-semibold">设置可接受的每日强度</h2>
              <div className="grid gap-4 sm:grid-cols-3">
                <NumberField
                  required
                  label="最多步行（km / 天）"
                  value={input.limits.max_daily_walking_km}
                  min={0.1}
                  max={100}
                  onChange={(v) =>
                    update({ ...input, limits: { ...input.limits, max_daily_walking_km: v ?? 8 } })
                  }
                />
                <NumberField
                  required
                  label="最多活动加交通（小时 / 天）"
                  value={input.limits.max_daily_active_hours}
                  min={0.1}
                  max={24}
                  onChange={(v) =>
                    update({
                      ...input,
                      limits: { ...input.limits, max_daily_active_hours: v ?? 8 },
                    })
                  }
                />
                <NumberField
                  required
                  label="至少专门休息（分钟 / 天）"
                  value={input.limits.min_daily_rest_minutes}
                  max={480}
                  onChange={(v) =>
                    update({
                      ...input,
                      limits: { ...input.limits, min_daily_rest_minutes: v ?? 45 },
                    })
                  }
                />
              </div>
              <p className="mt-2 text-xs text-ink-muted">
                按同行人的实际偏好填写。默认值只是可修改的规划阈值，用餐和空白时间不自动计入休息。
              </p>
            </section>
            <section className="space-y-3" aria-label="预算明细">
              <h2 className="text-lg font-semibold">整趟费用</h2>
              <p className="text-xs text-ink-muted">
                所有金额使用全部同行人的人民币总额。留空代表未知；确定免费才填写 0。
              </p>
              {input.costs.map((cost, index) => (
                <div
                  className="grid items-end gap-3 border-b border-stroke/50 pb-3 sm:grid-cols-[2fr_1fr_1fr_1fr_auto]"
                  key={cost.item_id}
                >
                  <Field label="费用项目">
                    <input
                      className={inputClass}
                      required
                      maxLength={200}
                      value={cost.name}
                      onChange={(e) =>
                        update({
                          ...input,
                          costs: input.costs.map((c, i) =>
                            i === index ? { ...c, name: e.target.value } : c
                          ),
                        })
                      }
                    />
                  </Field>
                  <NumberField
                    label="金额 / 下界（元）"
                    value={cost.amount_cny}
                    max={1e10}
                    onChange={(v) =>
                      update({
                        ...input,
                        costs: input.costs.map((c, i) =>
                          i === index ? { ...c, amount_cny: v, source_ids: [] } : c
                        ),
                      })
                    }
                  />
                  <NumberField
                    label="可选上界（元）"
                    value={cost.upper_cny}
                    min={cost.amount_cny ?? 0}
                    max={1e10}
                    onChange={(v) =>
                      update({
                        ...input,
                        costs: input.costs.map((c, i) =>
                          i === index ? { ...c, upper_cny: v, source_ids: [] } : c
                        ),
                      })
                    }
                  />
                  <Field label="金额依据">
                    <select
                      className={inputClass}
                      value={cost.basis}
                      onChange={(e) =>
                        update({
                          ...input,
                          costs: input.costs.map((c, i) =>
                            i === index ? { ...c, basis: e.target.value as typeof c.basis } : c
                          ),
                        })
                      }
                    >
                      <option value="estimate">估算</option>
                      <option value="quote">报价</option>
                      <option value="paid">已付</option>
                    </select>
                  </Field>
                  <button
                    type="button"
                    className={buttonClass}
                    aria-label={`删除费用 ${index + 1}`}
                    onClick={() =>
                      update({ ...input, costs: input.costs.filter((_, i) => i !== index) })
                    }
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              ))}
              <button
                className={buttonClass}
                type="button"
                onClick={() =>
                  update({
                    ...input,
                    costs: [
                      ...input.costs,
                      {
                        item_id: crypto.randomUUID(),
                        name: '',
                        amount_cny: null,
                        basis: 'estimate',
                      },
                    ],
                  })
                }
              >
                <Plus size={15} />
                添加费用
              </button>
              <label className="flex min-h-11 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={input.costs_complete}
                  onChange={(e) => update({ ...input, costs_complete: e.target.checked })}
                />
                费用明细已覆盖全部同行人的整趟旅行
              </label>
            </section>
            <section className="space-y-4" aria-label="逐日资料">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-lg font-semibold">逐日核对</h2>
                <button
                  type="button"
                  className={buttonClass}
                  disabled={input.days.length >= 31 || !input.days[input.days.length - 1].date}
                  onClick={() =>
                    update({
                      ...input,
                      days: [
                        ...input.days,
                        blankDay(dateOffset(input.days[input.days.length - 1].date, 1)),
                      ],
                    })
                  }
                >
                  <Plus size={15} />
                  添加一天
                </button>
              </div>
              {input.days.map((day, index) => (
                <details
                  className="border border-stroke p-4"
                  key={day.day_id}
                  open={index === 0}
                  id={`risk-day-${day.day_id}`}
                >
                  <summary className="min-h-8 cursor-pointer font-medium">
                    第 {index + 1} 天 · {day.date} · {day.destination || '待填目的地'}
                  </summary>
                  <div className="mt-4 space-y-5">
                    <div className="grid items-end gap-3 sm:grid-cols-[1fr_2fr_auto]">
                      <Field label="日期">
                        <input
                          className={inputClass}
                          type="date"
                          required
                          value={day.date}
                          onChange={(e) => updateDay(index, { date: e.target.value })}
                        />
                      </Field>
                      <Field label="目的地 / 当日主题">
                        <input
                          className={inputClass}
                          maxLength={200}
                          value={day.destination}
                          onChange={(e) => updateDay(index, { destination: e.target.value })}
                        />
                      </Field>
                      <button
                        type="button"
                        className={buttonClass}
                        disabled={input.days.length <= 1}
                        onClick={() =>
                          update({ ...input, days: input.days.filter((_, i) => i !== index) })
                        }
                      >
                        删除这天
                      </button>
                    </div>
                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                      <NumberField
                        label="户外活动（小时）"
                        value={day.outdoor_minutes == null ? null : day.outdoor_minutes / 60}
                        max={24}
                        onChange={(v) =>
                          updateDay(index, { outdoor_minutes: v == null ? null : v * 60 })
                        }
                      />
                      <NumberField
                        label="活动加交通（小时）"
                        value={day.active_minutes == null ? null : day.active_minutes / 60}
                        max={48}
                        onChange={(v) =>
                          updateDay(index, { active_minutes: v == null ? null : v * 60 })
                        }
                      />
                      <NumberField
                        label="步行距离（km）"
                        value={day.walking_km}
                        max={200}
                        onChange={(v) => updateDay(index, { walking_km: v })}
                      />
                      <NumberField
                        label="专门休息（分钟）"
                        value={day.rest_minutes}
                        max={1440}
                        onChange={(v) => updateDay(index, { rest_minutes: v })}
                      />
                    </div>
                    <div>
                      <h3 className="mb-3 font-medium">天气资料</h3>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <Field label="资料类型">
                          <select
                            className={inputClass}
                            value={day.weather.data_kind}
                            onChange={(e) =>
                              updateWeather(index, {
                                data_kind: e.target.value as RiskWeather['data_kind'],
                              })
                            }
                          >
                            <option value="unavailable">尚无资料</option>
                            <option value="forecast">对应日期预报</option>
                            <option value="seasonal_baseline">季节参考，非预报</option>
                          </select>
                        </Field>
                        <Field label="资料采集时间（北京时间）">
                          <input
                            className={inputClass}
                            type="datetime-local"
                            value={weatherTime(day.weather.observed_at)}
                            onChange={(e) =>
                              updateWeather(index, {
                                observed_at: e.target.value ? `${e.target.value}:00+08:00` : null,
                              })
                            }
                          />
                        </Field>
                      </div>
                      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
                        <NumberField
                          label="降水概率（%）"
                          value={day.weather.precipitation_probability_pct}
                          max={100}
                          onChange={(v) =>
                            updateWeather(index, { precipitation_probability_pct: v })
                          }
                        />
                        <NumberField
                          label="降水量（mm / 日）"
                          value={day.weather.precipitation_mm}
                          onChange={(v) => updateWeather(index, { precipitation_mm: v })}
                        />
                        <NumberField
                          label="最高温（℃）"
                          min={-100}
                          max={70}
                          value={day.weather.high_c}
                          onChange={(v) => updateWeather(index, { high_c: v })}
                        />
                        <NumberField
                          label="最低温（℃）"
                          min={-100}
                          max={70}
                          value={day.weather.low_c}
                          onChange={(v) => updateWeather(index, { low_c: v })}
                        />
                        <NumberField
                          label="风速（km/h）"
                          value={day.weather.wind_speed_kph}
                          onChange={(v) => updateWeather(index, { wind_speed_kph: v })}
                        />
                        <Field label="天气现象">
                          <select
                            className={inputClass}
                            value={day.weather.condition_code ?? ''}
                            onChange={(e) =>
                              updateWeather(index, { condition_code: numberValue(e.target.value) })
                            }
                          >
                            <option value="">未知</option>
                            {[
                              [0, '晴'],
                              [2, '多云'],
                              [45, '雾'],
                              [61, '小雨'],
                              [65, '大雨'],
                              [73, '雪'],
                              [95, '雷暴'],
                            ].map(([code, title]) => (
                              <option value={code} key={code}>
                                {title}
                              </option>
                            ))}
                            {day.weather.condition_code != null &&
                              ![0, 2, 45, 61, 65, 73, 95].includes(day.weather.condition_code) && (
                                <option value={day.weather.condition_code}>
                                  天气代码 {day.weather.condition_code}
                                </option>
                              )}
                          </select>
                        </Field>
                      </div>
                      <p className="mt-2 break-words text-xs text-ink-muted">
                        来源：{day.weather.source_label || '手动录入，未经外部核验'}
                      </p>
                    </div>
                    <div className="space-y-3">
                      <h3 className="font-medium">交通与衔接</h3>
                      {day.transports.map((leg, legIndex) => (
                        <div key={leg.item_id} className="space-y-2 border-b border-stroke pb-3">
                          <Field label="路线名称">
                            <input
                              className={inputClass}
                              required
                              maxLength={200}
                              value={leg.name}
                              onChange={(e) =>
                                updateDay(index, {
                                  transports: day.transports.map((t, i) =>
                                    i === legIndex
                                      ? { ...t, name: e.target.value, source_ids: [] }
                                      : t
                                  ),
                                })
                              }
                            />
                          </Field>
                          <div className="grid gap-3 sm:grid-cols-3">
                            <NumberField
                              label="需要交通时间（分钟）"
                              max={10080}
                              value={leg.duration_minutes}
                              onChange={(v) =>
                                updateDay(index, {
                                  transports: day.transports.map((t, i) =>
                                    i === legIndex
                                      ? {
                                          ...t,
                                          duration_minutes: v,
                                          available_minutes: t.available_minutes ?? v,
                                          source_ids: [],
                                        }
                                      : t
                                  ),
                                })
                              }
                            />
                            <NumberField
                              label="安排可用时间（分钟）"
                              max={10080}
                              value={leg.available_minutes}
                              onChange={(v) =>
                                updateDay(index, {
                                  transports: day.transports.map((t, i) =>
                                    i === legIndex
                                      ? { ...t, available_minutes: v, source_ids: [] }
                                      : t
                                  ),
                                })
                              }
                            />
                            <Field label="路线依据">
                              <select
                                className={inputClass}
                                value={leg.route_status}
                                onChange={(e) =>
                                  updateDay(index, {
                                    transports: day.transports.map((t, i) =>
                                      i === legIndex
                                        ? {
                                            ...t,
                                            route_status: e.target.value as typeof t.route_status,
                                          }
                                        : t
                                    ),
                                  })
                                }
                              >
                                <option value="missing">尚未核对</option>
                                <option value="estimated">仅为估算</option>
                                <option value="ready">已核对</option>
                              </select>
                            </Field>
                          </div>
                          <button
                            type="button"
                            className="min-h-11 text-sm text-ink-secondary underline"
                            onClick={() =>
                              updateDay(index, {
                                transports: day.transports.filter((_, i) => i !== legIndex),
                              })
                            }
                          >
                            删除这段交通
                          </button>
                        </div>
                      ))}
                      <button
                        type="button"
                        className={buttonClass}
                        onClick={() =>
                          updateDay(index, {
                            transports: [
                              ...day.transports,
                              {
                                item_id: crypto.randomUUID(),
                                name: '',
                                route_status: 'missing',
                                duration_minutes: null,
                                available_minutes: null,
                              },
                            ],
                          })
                        }
                      >
                        添加一段交通
                      </button>
                      {day.connections.map((connection, connectionIndex) => (
                        <div key={connectionIndex} className="grid items-end gap-3 sm:grid-cols-3">
                          <Field label="衔接名称">
                            <input
                              className={inputClass}
                              required
                              maxLength={200}
                              value={connection.name}
                              onChange={(e) =>
                                updateDay(index, {
                                  connections: day.connections.map((c, i) =>
                                    i === connectionIndex ? { ...c, name: e.target.value } : c
                                  ),
                                })
                              }
                            />
                          </Field>
                          <NumberField
                            required
                            label="可用间隔（分钟，可为负）"
                            min={-10080}
                            max={10080}
                            value={connection.available_minutes}
                            onChange={(v) =>
                              updateDay(index, {
                                connections: day.connections.map((c, i) =>
                                  i === connectionIndex ? { ...c, available_minutes: v ?? 0 } : c
                                ),
                              })
                            }
                          />
                          <div>
                            <NumberField
                              required
                              label="所需最小间隔（分钟）"
                              min={1}
                              max={1440}
                              value={connection.required_minutes}
                              onChange={(v) =>
                                updateDay(index, {
                                  connections: day.connections.map((c, i) =>
                                    i === connectionIndex ? { ...c, required_minutes: v ?? 30 } : c
                                  ),
                                })
                              }
                            />
                            <button
                              type="button"
                              className="min-h-11 text-sm underline"
                              onClick={() =>
                                updateDay(index, {
                                  connections: day.connections.filter(
                                    (_, i) => i !== connectionIndex
                                  ),
                                })
                              }
                            >
                              删除衔接
                            </button>
                          </div>
                        </div>
                      ))}
                      <button
                        type="button"
                        className={buttonClass}
                        onClick={() =>
                          updateDay(index, {
                            connections: [
                              ...day.connections,
                              { name: '换乘', available_minutes: 30, required_minutes: 60 },
                            ],
                          })
                        }
                      >
                        添加换乘 / 活动衔接
                      </button>
                      <label className="flex min-h-11 items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={day.transport_complete}
                          onChange={(e) =>
                            updateDay(index, { transport_complete: e.target.checked })
                          }
                        />
                        已完整核对这天所有交通；若无需交通，也在此确认
                      </label>
                    </div>
                  </div>
                </details>
              ))}
            </section>
            <div className="flex flex-wrap items-center gap-4 border-t border-stroke pt-5">
              <button
                className="inline-flex min-h-12 items-center justify-center gap-2 rounded-lg bg-accent px-6 py-3 font-medium text-white disabled:opacity-50"
                type="submit"
              >
                {busy ? '正在计算…' : '评估这个方案'}
                <ArrowRight size={17} />
              </button>
              <p className="text-xs text-ink-muted">
                按你录入或导入的资料计算，评估本身不调用付费模型。
              </p>
            </div>
          </fieldset>
        </form>
        {error && (
          <div role="alert" className="border border-red-200 bg-red-50 p-4 text-sm text-red-900">
            {error}
          </div>
        )}
        {report && (
          <section
            ref={resultRef}
            aria-label="风险评估结果"
            aria-live="polite"
            className="space-y-6 border-t-2 border-ink pt-6"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="mb-3 flex items-center gap-3">
                  <h2 className="text-xl font-semibold">评估结果</h2>
                  <Badge level={report.overall_level} />
                </div>
                <p className="max-w-2xl text-base leading-relaxed">{report.summary}</p>
                <p className="mt-2 text-xs text-ink-muted">
                  {new Date(report.assessed_at).toLocaleString('zh-CN')} ·{' '}
                  {report.is_example
                    ? '演示数据'
                    : report.input_origin === 'journeypilot'
                      ? '已有行程'
                      : '手动输入'}{' '}
                  · {report.data_complete ? '四项资料完整' : '存在待补资料'} ·{' '}
                  {report.engine_version}
                </p>
              </div>
              <button className={buttonClass} onClick={exportReport}>
                <Download size={15} />
                保存评估 JSON
              </button>
              <button className={buttonClass} disabled={busy} onClick={() => void optimize()}>
                生成优化草稿并再评估
              </button>
            </div>
            {report.dimensions.map((dimension) => (
              <section
                key={dimension.category}
                className="space-y-3 border-t border-stroke pt-5"
                aria-label={`${dimension.label}结果`}
              >
                <div className="flex flex-wrap items-center gap-3">
                  <h3 className="text-lg font-semibold">{dimension.label}</h3>
                  <Badge level={dimension.level} />
                </div>
                {dimension.category === 'budget' && (
                  <p className="text-sm text-ink-secondary">
                    已录入费用 ¥{dimension.metrics.recorded_min_cny ?? '未知'}–¥
                    {dimension.metrics.recorded_max_cny ?? '未知'}；预算上限 ¥
                    {dimension.metrics.budget_cap_cny ?? '未知'}。
                  </p>
                )}
                {dimension.findings.length === 0 && (
                  <p className="text-sm text-ink-secondary">{dimension.summary}。</p>
                )}
                {dimension.findings.map((finding, i) => (
                  <article
                    className="border-l-2 border-stroke pl-4"
                    key={`${finding.rule_id}-${finding.day_id}-${i}`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <h4 className="font-medium">{finding.title}</h4>
                      <Badge level={finding.level} />
                    </div>
                    <RiskExplanationChain
                      explanation={finding.explanation}
                      suggestion={finding.suggestion}
                    />
                    <p className="mt-2 text-xs text-ink-muted">规则：{finding.rule_id}</p>
                    {finding.day_id && (
                      <a
                        className="mt-1 inline-flex min-h-11 items-center text-sm text-accent underline"
                        href={`#risk-day-${finding.day_id}`}
                      >
                        核对这一天的输入
                      </a>
                    )}
                  </article>
                ))}
                <details
                  open={dimension.findings.length === 0}
                  className="rounded-card border border-stroke p-3"
                >
                  <summary className="min-h-8 cursor-pointer text-sm font-medium">
                    {dimension.level === 'unknown'
                      ? '为什么暂时无法判断'
                      : '查看本项汇总依据与完整输入'}
                  </summary>
                  <RiskExplanationChain explanation={dimension.explanation} />
                </details>
                {dimension.missing_data.length > 0 && (
                  <details className="bg-stone-100/70 p-3">
                    <summary className="min-h-8 cursor-pointer text-sm font-medium">
                      待补充 {dimension.missing_data.length} 项
                    </summary>
                    <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-relaxed text-ink-secondary">
                      {dimension.missing_data.map((text, i) => (
                        <li key={i}>{text}</li>
                      ))}
                    </ul>
                  </details>
                )}
              </section>
            ))}
            <details className="border-t border-stroke pt-4">
              <summary className="min-h-11 cursor-pointer text-sm font-medium">
                查看本次评估规则与假设
              </summary>
              <ul className="list-disc space-y-2 pl-5 text-sm leading-relaxed text-ink-secondary">
                {report.assumptions.map((text) => (
                  <li key={text}>{text}</li>
                ))}
              </ul>
              {report.bundle_id && (
                <p className="mt-3 break-all text-xs text-ink-muted">
                  对应行程版本：{report.bundle_id}。重新导入可核对最新方案。
                </p>
              )}
            </details>
            {optimization && (
              <RiskOptimizationLoop
                plan={optimization}
                busy={busy}
                applied={optimizationApplied}
                onApply={applyOptimization}
              />
            )}
          </section>
        )}
        <p className="text-xs leading-relaxed text-ink-muted">
          手动输入和未保存的评估只保留在本次页面中。需要保留结果时，请下载评估记录。
        </p>
      </div>
    </PageShell>
  );
};
