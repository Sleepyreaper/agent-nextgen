-- =====================================================================
-- Agent Evaluation Results — Azure AI Evaluation SDK quality metrics
-- =====================================================================
-- Stores per-agent, per-student quality scores from the Azure AI
-- Evaluation SDK (groundedness, coherence, relevance, fluency) plus
-- custom metrics like inter-agent agreement and outcome correlation.
--
-- Each row is one evaluator applied to one agent's output for one student.
-- Rows from the same evaluation run share a batch_id for grouping.

CREATE TABLE IF NOT EXISTS agent_evaluation_results (
    evaluation_result_id SERIAL PRIMARY KEY,
    application_id       INTEGER REFERENCES Applications(application_id) ON DELETE CASCADE,
    agent_name           VARCHAR(100) NOT NULL,
    evaluator_name       VARCHAR(100) NOT NULL,           -- 'groundedness', 'coherence', 'relevance', 'fluency', 'similarity', 'outcome_accuracy'
    score                NUMERIC(5,2),                    -- 1-5 for SDK evaluators, 0-100 for custom
    reason               TEXT,                            -- SDK-provided explanation or custom note
    batch_id             VARCHAR(100),                    -- Groups results from same run
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_eval_results_app_id     ON agent_evaluation_results(application_id);
CREATE INDEX IF NOT EXISTS idx_eval_results_agent      ON agent_evaluation_results(agent_name);
CREATE INDEX IF NOT EXISTS idx_eval_results_evaluator  ON agent_evaluation_results(evaluator_name);
CREATE INDEX IF NOT EXISTS idx_eval_results_batch      ON agent_evaluation_results(batch_id);
CREATE INDEX IF NOT EXISTS idx_eval_results_created    ON agent_evaluation_results(created_at);

-- =====================================================================
-- Evaluation Run Summary — aggregate metrics per batch run
-- =====================================================================
-- One row per evaluation run. Stores aggregate scores and metadata
-- so the dashboard can quickly show historical trends without
-- re-aggregating individual results every time.

CREATE TABLE IF NOT EXISTS agent_evaluation_runs (
    run_id               SERIAL PRIMARY KEY,
    batch_id             VARCHAR(100) UNIQUE NOT NULL,
    status               VARCHAR(50) DEFAULT 'running',   -- running, completed, failed
    started_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at         TIMESTAMP,
    total_students       INTEGER DEFAULT 0,
    total_evaluations    INTEGER DEFAULT 0,
    -- Aggregate scores (averages across all students)
    avg_groundedness     NUMERIC(5,2),
    avg_coherence        NUMERIC(5,2),
    avg_relevance        NUMERIC(5,2),
    avg_fluency          NUMERIC(5,2),
    -- Inter-agent agreement
    merlin_gaston_agreement NUMERIC(5,2),                 -- % same recommendation tier
    merlin_gaston_score_corr NUMERIC(5,4),                -- Pearson correlation
    -- Outcome accuracy (training students only)
    outcome_accuracy     NUMERIC(5,2),                    -- % correct vs was_selected
    outcome_precision    NUMERIC(5,2),
    outcome_recall       NUMERIC(5,2),
    outcome_f1           NUMERIC(5,2),
    -- Metadata
    evaluators_used      TEXT,                             -- comma-separated list
    agents_evaluated     TEXT,                             -- comma-separated list
    error_message        TEXT,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_eval_runs_batch   ON agent_evaluation_runs(batch_id);
CREATE INDEX IF NOT EXISTS idx_eval_runs_status  ON agent_evaluation_runs(status);
CREATE INDEX IF NOT EXISTS idx_eval_runs_created ON agent_evaluation_runs(created_at);
