'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { motionToken } from '@/lib/motion/controller';
import { useMotionRegistration } from '@/lib/motion/useMotion';
import type { TheatreTrace } from '@/lib/types';

/**
 * The live answer theatre (13.4) — band 6.
 *
 * An agent answering a real question, unattended, on a loop. It converts better
 * than a screenshot because it shows the product doing the thing the product is
 * for — and it is only worth anything if what it shows is true.
 *
 * So: this replays a *recorded execution trace*. The tokens, the tool calls,
 * the rows scanned, the latency and the cost all came out of a real run against
 * the demo tier, and the panel says when. There is no code path here that
 * composes an answer, and there is nowhere for one to be added: the component
 * takes a trace or it renders nothing.
 *
 * The tool-trace rail is visible by default rather than behind a toggle. An
 * answer whose evidence is one click away is an answer most visitors will never
 * check.
 *
 * The loop stops permanently after the rubric's cycle count without
 * interaction. A panel still replaying itself on a tab someone left open an
 * hour ago is spending their battery to say something they already heard.
 */

/**
 * The choreography, in the order 13.4 states it: the question types, a thinking
 * indicator names the tool, the headline streams, the chart draws, rows stagger
 * in, citations land last, then the panel holds.
 */
type Stage =
  | 'typing'
  | 'thinking'
  | 'headline'
  | 'chart'
  | 'rows'
  | 'citations'
  | 'hold';

export function AnswerTheatre({ traces }: { traces: TheatreTrace[] }) {
  const [index, setIndex] = useState(0);
  // The server renders the completed answer — chart drawn, table full — which
  // is both the reduced-motion frame and the frame a visitor with no
  // JavaScript keeps. The choreography then starts from it rather than
  // replacing an empty box, so the band never grows after paint.
  const [stage, setStage] = useState<Stage>('hold');
  const [typed, setTyped] = useState(traces[0]?.question ?? '');
  const [rowsShown, setRowsShown] = useState(traces[0]?.answer.table.rows?.length ?? 0);
  const [paused, setPaused] = useState(false);
  const [interacted, setInteracted] = useState(false);
  const cycles = useRef(0);
  const panelRef = useRef<HTMLDivElement | null>(null);

  const trace = traces[index];
  const rows = useMemo(() => trace?.answer.table.rows ?? [], [trace]);

  const complete = useCallback(() => {
    // Everything at once: the completed answer, chart drawn, table full. This
    // is what a reduced-motion visitor sees, and it is what the panel settles
    // into at the end of every cycle.
    setStage('hold');
    setTyped(trace?.question ?? '');
    setRowsShown(rows.length);
  }, [trace, rows.length]);

  const restart = useCallback(() => {
    setStage('typing');
    setTyped('');
    setRowsShown(0);
  }, []);

  const choose = useCallback(
    (next: number) => {
      setInteracted(true);
      cycles.current = 0;
      setIndex(((next % traces.length) + traces.length) % traces.length);
      restart();
    },
    [traces.length, restart],
  );

  useMotionRegistration(() => {
    const panel = panelRef.current;
    if (!panel || !trace) return null;

    let elapsed = 0;
    const perSecond = motionToken('--motion-second-ms', 1);
    const cps = motionToken('--theatre-type-cps', 0);
    const thinking = motionToken('--theatre-thinking-ms', 0);
    const chart = motionToken('--theatre-chart-draw-ms', 0);
    const stagger = motionToken('--theatre-row-stagger-ms', 0);
    const hold = motionToken('--theatre-hold-ms', 0);
    const maxCycles = motionToken('--theatre-max-cycles', 0);

    return {
      id: 'answer-theatre',
      klass: 'narrative' as const,
      el: panel,
      start() {
        elapsed = 0;
        restart();
      },
      pause() {},
      resume() {},
      renderStatic: complete,
      tick(sinceLastFrame: number) {
        if (paused) return;
        elapsed += sinceLastFrame;

        const question = trace.question;
        const typingMs = (question.length / cps) * perSecond;
        const rowsMs = rows.length * stagger;

        if (elapsed < typingMs) {
          setStage('typing');
          setTyped(question.slice(0, Math.ceil((elapsed / typingMs) * question.length)));
          return;
        }
        setTyped(question);

        const afterThinking = typingMs + thinking;
        if (elapsed < afterThinking) {
          setStage('thinking');
          return;
        }

        const afterHeadline = afterThinking + chart;
        if (elapsed < afterHeadline) {
          setStage('headline');
          return;
        }

        const afterChart = afterHeadline + chart;
        if (elapsed < afterChart) {
          setStage('chart');
          return;
        }

        const afterRows = afterChart + rowsMs;
        if (elapsed < afterRows) {
          setStage('rows');
          setRowsShown(Math.ceil(((elapsed - afterChart) / rowsMs) * rows.length));
          return;
        }
        setRowsShown(rows.length);

        const afterCitations = afterRows + chart;
        if (elapsed < afterCitations) {
          setStage('citations');
          return;
        }

        setStage('hold');
        if (elapsed < afterCitations + hold) return;

        elapsed = 0;
        if (!interacted) {
          cycles.current += 1;
          if (cycles.current >= maxCycles) {
            setPaused(true);
            complete();
            return;
          }
        }
        setIndex((current) => (current + 1) % traces.length);
        restart();
      },
    };
  }, [trace, paused, interacted, traces.length, restart]);

  useEffect(() => {
    if (!trace) complete();
  }, [trace, complete]);

  if (!trace) {
    // No eligible recorded trace means the estate has nothing it can honestly
    // show. The band collapses rather than showing a placeholder answer.
    return null;
  }

  const showAnswer = stage !== 'typing' && stage !== 'thinking';

  return (
    <section className="theatre" aria-labelledby="theatre-heading" ref={panelRef}>
      <div className="theatre-head">
        <div>
          <h2 id="theatre-heading" className="band-heading">
            Watch an agent answer
          </h2>
          <p className="band-sub">
            A replay of a real execution against the demo tier — the same tokens, tool
            calls, rows and cost. Recorded{' '}
            <time dateTime={trace.recorded_at}>{trace.recorded_at.split('T')[0]}</time>,
            and re-recorded nightly, so an answer that stopped being right stops
            being shown.
          </p>
        </div>
        <div className="theatre-controls">
          <button
            type="button"
            className="theatre-control"
            aria-pressed={paused}
            onClick={() => {
              setInteracted(true);
              setPaused((current) => !current);
            }}
          >
            {paused ? 'Play' : 'Pause'}
          </button>
          <button
            type="button"
            className="theatre-control"
            onClick={() => {
              setInteracted(true);
              restart();
            }}
          >
            Restart
          </button>
          <button type="button" className="theatre-control" onClick={() => choose(index - 1)}>
            Previous
          </button>
          <button type="button" className="theatre-control" onClick={() => choose(index + 1)}>
            Next
          </button>
        </div>
      </div>

      <label className="theatre-picker">
        <span className="sr-only">Choose a question</span>
        <select
          value={index}
          onChange={(event) => choose(Number(event.target.value))}
          className="theatre-select"
        >
          {traces.map((option, position) => (
            <option key={option.exchange_id} value={position}>
              {option.agent_name} — {option.question}
            </option>
          ))}
        </select>
      </label>

      <div className="theatre-body">
        <div className="theatre-stage">
          <p className="theatre-question">
            {typed}
            {stage === 'typing' ? <span className="theatre-caret" aria-hidden /> : null}
          </p>

          {stage === 'thinking' ? (
            <p className="theatre-thinking">
              Calling {trace.trace.tool_calls[0]?.tool ?? 'the runtime'}…
            </p>
          ) : null}

          {showAnswer ? (
            <>
              <p className="theatre-headline">{trace.answer.headline}</p>
              <p className="theatre-narrative">{trace.answer.narrative}</p>

              <Chart trace={trace} drawn={stage !== 'headline'} />

              <div className="answer-table-wrap">
                <table className="answer-table">
                  <caption className="sr-only">{trace.answer.headline}</caption>
                  <thead>
                    <tr>
                      {(trace.answer.table.columns ?? []).map((column) => (
                        <th key={column} scope="col">
                          {column}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.slice(0, rowsShown).map((row, position) => (
                      <tr key={String(row[0]) + String(position)}>
                        {row.map((cell, cellIndex) => (
                          <td
                            key={`${position}-${cellIndex}`}
                            className={typeof cell === 'number' ? 'tabular-nums' : undefined}
                          >
                            {cell === null ? '—' : String(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <ul className="theatre-citations" role="list">
                {trace.citations.map((citation) => (
                  <li key={citation.product_id} className="theatre-citation">
                    {citation.product_id}
                    {citation.as_of ? ` · as of ${citation.as_of.split('T')[0]}` : ''}
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </div>

        {/* Visible by default (13.4). The evidence is the point. */}
        <aside className="theatre-rail" aria-label="Tool trace">
          <h3 className="refusal-subhead">What it did</h3>
          <ol className="theatre-rail-list">
            {trace.trace.tool_calls.map((call, position) => (
              <li key={`${call.tool}-${position}`} className="theatre-rail-item">
                <p className="theatre-rail-tool">{call.tool}</p>
                <p className="theatre-rail-meta">
                  {call.rows_returned} of {call.rows_scanned} rows · {call.duration_ms}ms ·{' '}
                  {call.cost_class}
                </p>
              </li>
            ))}
          </ol>
          <dl className="theatre-rail-totals">
            <div>
              <dt>Runtime</dt>
              <dd>{trace.trace.runtime}</dd>
            </div>
            <div>
              <dt>Latency</dt>
              <dd className="tabular-nums">{trace.trace.latency_ms}ms</dd>
            </div>
            <div>
              <dt>Cost</dt>
              <dd className="tabular-nums">{trace.trace.cost_display}</dd>
            </div>
            <div>
              <dt>Confidence</dt>
              <dd className="tabular-nums">{trace.confidence_display}</dd>
            </div>
          </dl>
        </aside>
      </div>
    </section>
  );
}

/**
 * Bars growing from the axis, drawn with `transform` alone.
 *
 * A chart whose bars animate their height animates layout, which is the one
 * thing the animatable-props rule forbids and the reason the ribbon and this
 * panel can share a frame budget at all.
 */
function Chart({ trace, drawn }: { trace: TheatreTrace; drawn: boolean }) {
  const rows = trace.answer.table.rows ?? [];
  const values = rows.map((row) => (typeof row[1] === 'number' ? row[1] : 0));
  const peak = Math.max(...values, 0) || 1;

  if (values.length === 0) return null;

  return (
    <div className="theatre-chart" data-drawn={drawn} role="img"
         aria-label={`${trace.answer.visual.type ?? 'chart'} of ${trace.answer.headline}`}>
      {rows.map((row, position) => {
        const share = (values[position] ?? 0) / peak;
        return (
          <div key={String(row[0]) + String(position)} className="theatre-bar-slot">
            <div
              className="theatre-bar"
              style={{ transform: `scaleY(${drawn ? share : 0})` }}
            />
            <span className="theatre-bar-label">{String(row[0])}</span>
          </div>
        );
      })}
    </div>
  );
}
