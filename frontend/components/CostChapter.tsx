"use client";

import { byModel, byStage } from "@/lib/cost";
import { usd } from "@/lib/format";
import type { Project, ProvRecord, Routing } from "@/lib/types";

const per = (n: number) => n.toLocaleString();
const title = (s: string) => s[0].toUpperCase() + s.slice(1);

export function CostChapter({
  project,
  records,
  routing,
  allCost,
}: {
  project: Project;
  records: ProvRecord[];
  routing: Routing | null;
  allCost: number | null;
}) {
  const stages = byStage(records);
  const models = byModel(records);
  const total = models.reduce((a, m) => a + m.cost, 0);
  const routeOf = (stage: string) => routing?.stages.find((s) => s.stage === stage);

  return (
    <>
      <h2 className="ch-title">Cost</h2>
      <div className="totals">
        <div>
          <span className="v">{usd(project.cost_usd)}</span>
          <span className="cap">this project</span>
        </div>
        {allCost !== null && (
          <div>
            <span className="v">{usd(allCost)}</span>
            <span className="cap">all projects</span>
          </div>
        )}
      </div>

      {records.length === 0 ? (
        <p className="empty">Nothing spent yet.</p>
      ) : (
        <>
          <h3 className="sec">By stage</h3>
          <div className="scroll-x">
            <table className="ledger">
              <thead>
                <tr>
                  <th>Stage</th>
                  <th>Model</th>
                  <th className="r">Tokens in / out</th>
                  <th className="r">Cost</th>
                </tr>
              </thead>
              <tbody>
                {stages.map((s) => {
                  const route = routeOf(s.key);
                  return (
                    <StageRows
                      key={s.key}
                      label={s.label}
                      tier={route?.flavor}
                      reason={route?.reason}
                      tokens={`${per(s.tokensIn)} / ${per(s.tokensOut)}`}
                      cost={usd(s.cost, 5)}
                    />
                  );
                })}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={3}>Total</td>
                  <td className="r">{usd(total, 5)}</td>
                </tr>
              </tfoot>
            </table>
          </div>

          <h3 className="sec">By model</h3>
          <div className="scroll-x">
            <table className="ledger">
              <thead>
                <tr>
                  <th>Model</th>
                  <th className="r">Calls</th>
                  <th className="r">Cost</th>
                  <th>Share</th>
                </tr>
              </thead>
              <tbody>
                {models.map((m) => {
                  const pct = total ? (m.cost / total) * 100 : 0;
                  return (
                    <tr key={m.key}>
                      <td>
                        <span className="mtag">{m.label}</span>
                      </td>
                      <td className="r">{m.calls}</td>
                      <td className="r">{usd(m.cost, 5)}</td>
                      <td>
                        <span className="share">
                          <i style={{ width: `${pct}%` }} />
                          <span>{pct.toFixed(0)}%</span>
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {routing && (
        <p className="pricenote">
          List prices per 1M tokens, in / out:{" "}
          {(["nano", "super", "ultra"] as const).map((f, i) => {
            const s = routing.stages.find((x) => x.flavor === f);
            return s ? (
              <span key={f}>
                {i > 0 && " · "}
                {title(f)} {s.price_in.toFixed(2)} / {s.price_out.toFixed(2)}
              </span>
            ) : null;
          })}
          . Costs are estimated from logged tokens.
        </p>
      )}
    </>
  );
}

function StageRows({
  label,
  tier,
  reason,
  tokens,
  cost,
}: {
  label: string;
  tier?: string;
  reason?: string;
  tokens: string;
  cost: string;
}) {
  return (
    <>
      <tr className={reason ? "has-reason" : undefined}>
        <td>{label}</td>
        <td>
          <span className="mtag">{tier ? title(tier) : ""}</span>
        </td>
        <td className="r">{tokens}</td>
        <td className="r">{cost}</td>
      </tr>
      {reason && (
        <tr>
          <td className="reason" colSpan={4}>
            {reason}
          </td>
        </tr>
      )}
    </>
  );
}
