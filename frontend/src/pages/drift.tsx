import React from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Collapse from '@mui/material/Collapse';
import CircularProgress from '@mui/material/CircularProgress';
import LinearProgress from '@mui/material/LinearProgress';
import Tooltip from '@mui/material/Tooltip';
import Dialog from '@mui/material/Dialog';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import IconButton from '@mui/material/IconButton';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CancelIcon from '@mui/icons-material/Cancel';
import RemoveCircleOutlineIcon from '@mui/icons-material/RemoveCircleOutline';
import RefreshIcon from '@mui/icons-material/Refresh';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh';
import CloseIcon from '@mui/icons-material/Close';
import { motion } from 'framer-motion';
import AppShell from '@/app/components/Layout/AppShell';
import VendoredToolUi from '@/toolui/VendoredToolUi';
import { useClaudeTokens } from '@/shared/styles/ThemeContext';
import { DRIFT_SCAN_URL, DRIFT_FIX_URL } from '@/shared/state/API_ENDPOINTS';

interface Check {
  id: string;
  label: string;
  severity: 'high' | 'medium';
  fix: string;
  state: 'pass' | 'fail' | 'na';
  detail: string;
}

interface AppRow {
  id: string;
  name: string;
  path: string;
  is_self: boolean;
  has_backend: boolean;
  failed: number;
  applicable: number;
  passed: number;
  checks: Check[];
}

interface ScanResult {
  root: string;
  total: number;
  clean: number;
  drifted: number;
  checks: { id: string; label: string; severity: string; fix: string }[];
  apps: AppRow[];
}

interface FixFile {
  path: string;
  language: string;
  note: string;
  old_text: string;
  new_text: string;
  created: boolean;
}

interface FixResult {
  applied: boolean;
  dry_run?: boolean;
  app_id: string;
  files: FixFile[];
  targets: string[];
  skipped: { id: string; reason: string }[];
  reason?: string;
  blocked?: { path: string; problem: string }[];
  backup?: string;
  before?: { passed: number; applicable: number };
  after?: { passed: number; applicable: number };
}

/** Preview + confirm. The dialog only ever shows a server-computed plan, never a guess made here. */
const FixPreview: React.FC<{
  app: AppRow;
  onClose: () => void;
  onApplied: () => void;
}> = ({ app, onClose, onApplied }) => {
  const c = useClaudeTokens();
  const [plan, setPlan] = React.useState<FixResult | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [applying, setApplying] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [done, setDone] = React.useState<FixResult | null>(null);

  const post = React.useCallback(async (dryRun: boolean): Promise<FixResult> => {
    const res = await fetch(DRIFT_FIX_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app_id: app.id, dry_run: dryRun }),
    });
    const body = await res.json();
    // 422 is the syntax gate refusing to write, which carries a useful payload rather than an
    // error string; surface it as a result instead of throwing it away.
    if (!res.ok && res.status !== 422) {
      throw new Error(body?.detail || `request failed (${res.status})`);
    }
    return body as FixResult;
  }, [app.id]);

  React.useEffect(() => {
    let cancelled = false;
    post(true)
      .then((p) => { if (!cancelled) setPlan(p); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : 'preview failed'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [post]);

  const apply = async () => {
    setApplying(true);
    setError(null);
    try {
      const result = await post(false);
      setDone(result);
      if (result.applied) onApplied();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'apply failed');
    } finally {
      setApplying(false);
    }
  };

  const files = done?.files ?? plan?.files ?? [];
  const blocked = done?.blocked ?? plan?.blocked;

  return (
    <Dialog
      open
      onClose={onClose}
      maxWidth="lg"
      fullWidth
      PaperProps={{
        sx: {
          bgcolor: c.bg.page,
          backgroundImage: 'none',
          border: `1px solid ${c.border.subtle}`,
          borderRadius: `${c.radius.lg}px`,
        },
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1.5,
          px: 3,
          pt: 2.5,
          pb: 1.5,
        }}
      >
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography sx={{ fontSize: '1.1rem', fontWeight: 600, color: c.text.primary }}>
            {done?.applied ? 'Applied to' : 'Preview fix for'} {app.name}
          </Typography>
          <Typography sx={{ fontSize: '0.75rem', color: c.text.ghost, fontFamily: c.font.mono }}>
            {app.path}
          </Typography>
        </Box>
        <IconButton onClick={onClose} size="small" sx={{ color: c.text.tertiary }}>
          <CloseIcon sx={{ fontSize: 19 }} />
        </IconButton>
      </Box>

      <DialogContent sx={{ px: 3, pt: 0 }}>
        {loading && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 5, justifyContent: 'center' }}>
            <CircularProgress size={18} sx={{ color: c.accent.primary }} />
            <Typography sx={{ color: c.text.muted, fontSize: '0.88rem' }}>
              Computing patch…
            </Typography>
          </Box>
        )}

        {error && (
          <Box sx={{ p: 2, borderRadius: `${c.radius.md}px`, bgcolor: c.status.errorBg, mb: 2 }}>
            <Typography sx={{ color: c.status.error, fontSize: '0.85rem', fontWeight: 550 }}>
              {error}
            </Typography>
          </Box>
        )}

        {blocked && blocked.length > 0 && (
          <Box sx={{ p: 2, borderRadius: `${c.radius.md}px`, bgcolor: c.status.errorBg, mb: 2 }}>
            <Typography sx={{ color: c.status.error, fontSize: '0.85rem', fontWeight: 600, mb: 0.5 }}>
              Refused: the patched script did not parse. Nothing was written.
            </Typography>
            {blocked.map((b) => (
              <Typography
                key={b.path}
                sx={{ color: c.text.secondary, fontSize: '0.76rem', fontFamily: c.font.mono, mt: 0.5 }}
              >
                {b.path}: {b.problem}
              </Typography>
            ))}
          </Box>
        )}

        {done?.applied && (
          <Box sx={{ p: 2, borderRadius: `${c.radius.md}px`, bgcolor: c.status.successBg, mb: 2 }}>
            <Typography sx={{ color: c.status.success, fontSize: '0.88rem', fontWeight: 600 }}>
              {done.before?.passed}/{done.before?.applicable} → {done.after?.passed}/
              {done.after?.applicable} checks passing.
            </Typography>
            <Typography sx={{ color: c.text.secondary, fontSize: '0.78rem', mt: 0.5, lineHeight: 1.55 }}>
              Originals saved to <code>{done.backup}</code> inside the workspace. The backend picks
              these up on its next start; restart that app from OpenSwarm when you're ready. Nothing
              was restarted for you.
            </Typography>
          </Box>
        )}

        {!loading && files.length === 0 && !blocked?.length && (
          <Typography sx={{ color: c.text.muted, fontSize: '0.88rem', py: 3 }}>
            {plan?.reason ?? 'Nothing to change here.'}
          </Typography>
        )}

        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
          {files.map((f) => (
            <Box key={f.path}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.75, flexWrap: 'wrap' }}>
                <Typography
                  sx={{ fontSize: '0.82rem', fontWeight: 600, color: c.text.primary, fontFamily: c.font.mono }}
                >
                  {f.path}
                </Typography>
                {f.created && (
                  <Chip
                    label="new file"
                    size="small"
                    sx={{
                      height: 17,
                      fontSize: '0.6rem',
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      bgcolor: `${c.status.success}25`,
                      color: c.status.success,
                    }}
                  />
                )}
              </Box>
              <Typography sx={{ fontSize: '0.78rem', color: c.text.muted, mb: 1, lineHeight: 1.55 }}>
                {f.note}
              </Typography>
              <VendoredToolUi
                name="code-diff"
                props={{
                  id: `${app.id}-${f.path}`,
                  oldCode: f.old_text,
                  newCode: f.new_text,
                  language: f.language,
                  filename: f.path,
                  diffStyle: 'unified',
                  lineNumbers: 'visible',
                  maxCollapsedLines: 24,
                }}
              />
            </Box>
          ))}
        </Box>
      </DialogContent>

      <DialogActions sx={{ px: 3, pb: 2.5, pt: 1.5, gap: 1 }}>
        <Button
          onClick={onClose}
          sx={{ textTransform: 'none', borderRadius: 999, color: c.text.secondary }}
        >
          {done?.applied ? 'Close' : 'Cancel'}
        </Button>
        {!done?.applied && (
          <Button
            onClick={apply}
            disabled={applying || loading || files.length === 0}
            startIcon={
              applying ? (
                <CircularProgress size={14} sx={{ color: 'inherit' }} />
              ) : (
                <AutoFixHighIcon sx={{ fontSize: 17 }} />
              )
            }
            sx={{
              textTransform: 'none',
              borderRadius: 999,
              px: 2.25,
              bgcolor: c.accent.primary,
              color: '#fff',
              fontWeight: 550,
              '&:hover': { bgcolor: c.accent.hover },
              '&.Mui-disabled': { bgcolor: `${c.text.primary}12`, color: c.text.ghost },
            }}
          >
            {applying ? 'Applying…' : `Apply to ${files.length} file${files.length === 1 ? '' : 's'}`}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
};

const Stat: React.FC<{ value: React.ReactNode; label: string; color: string }> = ({
  value,
  label,
  color,
}) => {
  const c = useClaudeTokens();
  return (
    <Box
      sx={{
        flex: 1,
        minWidth: 130,
        bgcolor: c.bg.surface,
        border: `1px solid ${c.border.subtle}`,
        borderRadius: `${c.radius.lg}px`,
        px: 2.5,
        py: 2,
      }}
    >
      <Typography sx={{ fontSize: '1.9rem', fontWeight: 600, color, lineHeight: 1.1 }}>
        {value}
      </Typography>
      <Typography sx={{ fontSize: '0.78rem', color: c.text.muted, mt: 0.5 }}>{label}</Typography>
    </Box>
  );
};

const AppCard: React.FC<{ app: AppRow; onFixed: () => void }> = ({ app, onFixed }) => {
  const c = useClaudeTokens();
  const [open, setOpen] = React.useState(false);
  const [previewing, setPreviewing] = React.useState(false);
  const clean = app.failed === 0;
  // Denominator is the applicable checks, not all six: a frontend-only app is graded on what
  // actually applies to it rather than being credited for checks that never ran.
  const total = app.applicable;
  const passed = app.passed;

  return (
    <Box
      sx={{
        bgcolor: c.bg.surface,
        border: `1px solid ${app.is_self ? c.accent.primary : c.border.subtle}`,
        borderRadius: `${c.radius.lg}px`,
        overflow: 'hidden',
        transition: c.transition,
      }}
    >
      <Box
        onClick={() => setOpen((v) => !v)}
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1.5,
          px: 2.5,
          py: 1.75,
          cursor: 'pointer',
          '&:hover': { bgcolor: `${c.text.primary}05` },
        }}
      >
        {clean ? (
          <CheckCircleIcon sx={{ fontSize: 20, color: c.status.success }} />
        ) : (
          <CancelIcon sx={{ fontSize: 20, color: c.status.error }} />
        )}

        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography
              sx={{
                fontWeight: 550,
                fontSize: '0.95rem',
                color: c.text.primary,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {app.name}
            </Typography>
            {app.is_self && (
              <Chip
                label="this app"
                size="small"
                sx={{
                  height: 19,
                  fontSize: '0.65rem',
                  bgcolor: `${c.accent.primary}1A`,
                  color: c.accent.primary,
                  fontWeight: 600,
                }}
              />
            )}
            {!app.has_backend && (
              <Chip
                label="no backend"
                size="small"
                sx={{
                  height: 19,
                  fontSize: '0.65rem',
                  bgcolor: `${c.text.primary}0D`,
                  color: c.text.muted,
                }}
              />
            )}
          </Box>
          <Typography sx={{ fontSize: '0.72rem', color: c.text.ghost, fontFamily: c.font.mono }}>
            {app.id}
          </Typography>
        </Box>

        <Box sx={{ width: 90, flexShrink: 0 }}>
          <LinearProgress
            variant="determinate"
            value={total === 0 ? 0 : (passed / total) * 100}
            sx={{
              height: 5,
              borderRadius: 999,
              bgcolor: `${c.text.primary}12`,
              '& .MuiLinearProgress-bar': {
                bgcolor: clean ? c.status.success : c.status.error,
                borderRadius: 999,
              },
            }}
          />
          <Typography sx={{ fontSize: '0.68rem', color: c.text.muted, mt: 0.5, textAlign: 'right' }}>
            {passed}/{total} passing
          </Typography>
        </Box>

        {!clean && (
          <Tooltip title="Preview the exact patch before anything is written">
            <Button
              onClick={(e) => {
                e.stopPropagation();
                setPreviewing(true);
              }}
              startIcon={<AutoFixHighIcon sx={{ fontSize: 15 }} />}
              size="small"
              sx={{
                textTransform: 'none',
                borderRadius: 999,
                flexShrink: 0,
                px: 1.5,
                fontSize: '0.78rem',
                color: c.accent.primary,
                border: `1px solid ${c.accent.primary}40`,
                '&:hover': { bgcolor: `${c.accent.primary}12`, borderColor: c.accent.primary },
              }}
            >
              Fix
            </Button>
          </Tooltip>
        )}

        <ExpandMoreIcon
          sx={{
            fontSize: 20,
            color: c.text.tertiary,
            transform: open ? 'rotate(180deg)' : 'none',
            transition: c.transition,
          }}
        />
      </Box>

      {previewing && (
        <FixPreview app={app} onClose={() => setPreviewing(false)} onApplied={onFixed} />
      )}

      <Collapse in={open} unmountOnExit>
        <Box sx={{ px: 2.5, pb: 2.5, pt: 0.5, display: 'flex', flexDirection: 'column', gap: 1.25 }}>
          {app.checks.map((chk) => (
            <Box
              key={chk.id}
              sx={{
                display: 'flex',
                gap: 1.25,
                p: 1.5,
                borderRadius: `${c.radius.md}px`,
                bgcolor:
                  chk.state === 'pass'
                    ? c.status.successBg
                    : chk.state === 'fail'
                      ? c.status.errorBg
                      : `${c.text.primary}08`,
              }}
            >
              {chk.state === 'pass' ? (
                <CheckCircleIcon sx={{ fontSize: 17, color: c.status.success, mt: '2px' }} />
              ) : chk.state === 'fail' ? (
                <CancelIcon sx={{ fontSize: 17, color: c.status.error, mt: '2px' }} />
              ) : (
                <RemoveCircleOutlineIcon sx={{ fontSize: 17, color: c.text.ghost, mt: '2px' }} />
              )}
              <Box sx={{ flex: 1 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                  <Typography sx={{ fontSize: '0.85rem', fontWeight: 550, color: c.text.primary }}>
                    {chk.label}
                  </Typography>
                  {chk.state === 'na' && (
                    <Chip
                      label="n/a"
                      size="small"
                      sx={{
                        height: 17,
                        fontSize: '0.6rem',
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        bgcolor: `${c.text.primary}0D`,
                        color: c.text.muted,
                      }}
                    />
                  )}
                  {chk.state === 'fail' && (
                    <Chip
                      label={chk.severity}
                      size="small"
                      sx={{
                        height: 17,
                        fontSize: '0.6rem',
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        bgcolor:
                          chk.severity === 'high' ? `${c.status.error}25` : `${c.text.primary}12`,
                        color: chk.severity === 'high' ? c.status.error : c.text.muted,
                      }}
                    />
                  )}
                </Box>
                <Typography
                  sx={{ fontSize: '0.8rem', color: c.text.secondary, mt: 0.4, lineHeight: 1.5 }}
                >
                  {chk.detail}
                </Typography>
                {chk.state === 'fail' && (
                  <Typography
                    sx={{
                      fontSize: '0.76rem',
                      color: c.text.tertiary,
                      mt: 0.75,
                      fontFamily: c.font.mono,
                      lineHeight: 1.5,
                    }}
                  >
                    Fix: {chk.fix}
                  </Typography>
                )}
              </Box>
            </Box>
          ))}
        </Box>
      </Collapse>
    </Box>
  );
};

const BACKEND_ENABLED = process.env.BACKEND_ENABLED;

const Drift: React.FC = () => {
  const c = useClaudeTokens();
  const [data, setData] = React.useState<ScanResult | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [copied, setCopied] = React.useState(false);

  const runScan = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(DRIFT_SCAN_URL);
      if (!res.ok) throw new Error(`scan failed (${res.status})`);
      setData(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'scan failed');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    if (BACKEND_ENABLED) runScan();
    else {
      setLoading(false);
      setError('This app has no backend enabled, so the scan cannot run.');
    }
  }, [runScan]);

  const copyReport = () => {
    if (!data) return;
    const lines = data.apps
      .filter((a) => a.failed > 0)
      .map(
        (a) =>
          `${a.name} (${a.id}) — ${a.failed} failing\n` +
          a.checks
            .filter((k) => k.state === 'fail')
            .map((k) => `    [${k.severity}] ${k.label}: ${k.detail}`)
            .join('\n'),
      );
    navigator.clipboard.writeText(
      `Drift scan — ${data.drifted}/${data.total} workspaces drifted\n\n${lines.join('\n\n')}`,
    );
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  };

  return (
    <AppShell>
    <Box sx={{ maxWidth: 1000, mx: 'auto', px: { xs: 3, md: 5 }, py: 5 }}>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 2,
          flexWrap: 'wrap',
          mb: 3,
        }}
      >
        <Box>
          <Typography
            sx={{
              fontSize: '1.9rem',
              fontWeight: 600,
              color: c.text.primary,
              letterSpacing: '-0.02em',
            }}
          >
            Detect drift
          </Typography>
          <Typography sx={{ fontSize: '0.92rem', color: c.text.muted, mt: 0.75, maxWidth: 620 }}>
            Grades every app workspace in this OpenSwarm install against the six fixes this template
            carries. Read-only: it reads text files and stats one marker, and never runs or modifies
            anything belonging to another app.
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1 }}>
          {data && (
            <Tooltip title={copied ? 'Copied' : 'Copy failures as text'}>
              <Button
                onClick={copyReport}
                startIcon={<ContentCopyIcon sx={{ fontSize: 16 }} />}
                sx={{
                  textTransform: 'none',
                  borderRadius: 999,
                  color: c.text.secondary,
                  '&:hover': { bgcolor: `${c.text.primary}08` },
                }}
              >
                {copied ? 'Copied' : 'Copy'}
              </Button>
            </Tooltip>
          )}
          <Button
            onClick={runScan}
            disabled={loading || !BACKEND_ENABLED}
            startIcon={<RefreshIcon sx={{ fontSize: 17 }} />}
            sx={{
              textTransform: 'none',
              borderRadius: 999,
              px: 2.25,
              bgcolor: c.accent.primary,
              color: '#fff',
              fontWeight: 550,
              '&:hover': { bgcolor: c.accent.hover },
              '&.Mui-disabled': { bgcolor: `${c.text.primary}12`, color: c.text.ghost },
            }}
          >
            Rescan
          </Button>
        </Box>
      </Box>

      {loading && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 6, justifyContent: 'center' }}>
          <CircularProgress size={20} sx={{ color: c.accent.primary }} />
          <Typography sx={{ color: c.text.muted, fontSize: '0.9rem' }}>
            Scanning workspaces…
          </Typography>
        </Box>
      )}

      {error && !loading && (
        <Box
          sx={{
            p: 2.5,
            borderRadius: `${c.radius.lg}px`,
            bgcolor: c.status.errorBg,
            border: `1px solid ${c.status.error}30`,
          }}
        >
          <Typography sx={{ color: c.status.error, fontWeight: 550, fontSize: '0.9rem' }}>
            {error}
          </Typography>
        </Box>
      )}

      {data && !loading && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
        >
          <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap', mb: 3 }}>
            <Stat value={data.total} label="workspaces scanned" color={c.text.primary} />
            <Stat value={data.clean} label="fully configured" color={c.status.success} />
            <Stat value={data.drifted} label="drifted" color={c.status.error} />
            <Stat
              value={data.apps.reduce((n, a) => n + a.failed, 0)}
              label="failing checks total"
              color={c.text.secondary}
            />
          </Box>

          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
            {data.apps.map((app) => (
              <AppCard key={app.id} app={app} onFixed={runScan} />
            ))}
          </Box>

          <Typography
            sx={{ fontSize: '0.72rem', color: c.text.ghost, mt: 3, fontFamily: c.font.mono }}
          >
            root: {data.root}
          </Typography>
        </motion.div>
      )}
    </Box>
    </AppShell>
  );
};

export default Drift;
