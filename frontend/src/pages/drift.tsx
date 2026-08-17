import React from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Collapse from '@mui/material/Collapse';
import CircularProgress from '@mui/material/CircularProgress';
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

/** Which variant this one check's file matches. `neither` is the only value that is a defect: it
 *  means the file matches no variant's spelling, not that it is on the other side. */
type Side = 'template' | 'terminal' | 'neither' | 'na';

interface Check {
  id: string;
  label: string;
  severity: 'high' | 'medium';
  fix: string;
  state: 'pass' | 'fail' | 'na';
  side: Side;
  detail: string;
}

/** Neither template nor terminal is the correct one. `mixed` is the only state that is wrong. */
type Variant = 'template' | 'terminal' | 'mixed' | 'unknown';

/** "harden" converts a workspace to the template variant; "revert" converts it to terminal. */
type Direction = 'harden' | 'revert';

interface AppRow {
  id: string;
  name: string;
  path: string;
  is_self: boolean;
  has_backend: boolean;
  failed: number;
  applicable: number;
  passed: number;
  variant: Variant;
  /** Ids of checks BOTH variants pass that this workspace fails; converting sideways won't fix. */
  shared_missing: string[];
  checks: Check[];
}

interface ScanResult {
  root: string;
  total: number;
  variants: Record<Variant, number>;
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
  deleted: boolean;
}

interface FixResult {
  applied: boolean;
  dry_run?: boolean;
  app_id: string;
  direction: Direction;
  files: FixFile[];
  targets: string[];
  skipped: { id: string; reason: string }[];
  reason?: string;
  blocked?: { path: string; problem: string }[];
  backup?: string;
  before?: { passed: number; applicable: number };
  after?: { passed: number; applicable: number };
}

/** One place to name the two variants, so the page never invents a second vocabulary for them. */
const VARIANT_LABEL: Record<Variant, string> = {
  template: 'Template',
  terminal: 'Terminal',
  mixed: 'Mixed',
  unknown: 'Unknown',
};

const DIRECTION_TARGET: Record<Direction, Variant> = {
  harden: 'template',
  revert: 'terminal',
};

/** How one check row reads. Keyed on `side`, never on pass/fail: a row that matches Terminal is
 *  reporting which variant this file is written in, and colouring that red said the user's own
 *  deliberate conversion was damage. Only `neither` — matching no variant at all — is a defect. */
const SIDE_ROW: Record<Side, { label: string; tone: 'good' | 'bad' | 'quiet' }> = {
  template: { label: 'Template', tone: 'good' },
  terminal: { label: 'Terminal', tone: 'good' },
  neither: { label: 'Neither', tone: 'bad' },
  na: { label: 'n/a', tone: 'quiet' },
};

/** Preview + confirm. The dialog only ever shows a server-computed plan, never a guess made here. */
const FixPreview: React.FC<{
  app: AppRow;
  direction: Direction;
  onClose: () => void;
  onApplied: () => void;
}> = ({ app, direction, onClose, onApplied }) => {
  const c = useClaudeTokens();
  const [plan, setPlan] = React.useState<FixResult | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [applying, setApplying] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [done, setDone] = React.useState<FixResult | null>(null);
  const target = VARIANT_LABEL[DIRECTION_TARGET[direction]];

  const post = React.useCallback(async (dryRun: boolean): Promise<FixResult> => {
    const res = await fetch(DRIFT_FIX_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app_id: app.id, dry_run: dryRun, direction }),
    });
    const body = await res.json();
    // 422 is the syntax gate refusing to write, which carries a useful payload rather than an
    // error string; surface it as a result instead of throwing it away.
    if (!res.ok && res.status !== 422) {
      throw new Error(body?.detail || `request failed (${res.status})`);
    }
    return body as FixResult;
  }, [app.id, direction]);

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
            {done?.applied ? 'Converted' : 'Convert'} {app.name} to {target}
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
              Now on the {target} variant.
            </Typography>
            <Typography sx={{ color: c.text.secondary, fontSize: '0.78rem', mt: 0.5, lineHeight: 1.55 }}>
              Originals saved to <code>{done.backup}</code> inside the workspace. The backend picks
              these up on its next start; restart that app from OpenSwarm when you're ready. Nothing
              was restarted for you.
            </Typography>
          </Box>
        )}

        {/* Shared checks produce no edit in either direction. Silence here reads as the tool
            forgetting them, so the reason the server gave is shown rather than swallowed. */}
        {(done ?? plan)?.skipped?.length ? (
          <Box sx={{ p: 2, borderRadius: `${c.radius.md}px`, bgcolor: `${c.text.primary}08`, mb: 2 }}>
            {(done ?? plan)!.skipped.map((s) => (
              <Typography
                key={s.id}
                sx={{ color: c.text.muted, fontSize: '0.76rem', lineHeight: 1.6 }}
              >
                <Box component="span" sx={{ fontFamily: c.font.mono, color: c.text.secondary }}>
                  {s.id}
                </Box>{' '}
                — {s.reason}
              </Typography>
            ))}
          </Box>
        ) : null}

        {!loading && files.length === 0 && !blocked?.length && (
          <Typography sx={{ color: c.text.muted, fontSize: '0.88rem', py: 3 }}>
            {plan?.reason ?? `Already on the ${target} variant; nothing to change.`}
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
                {(f.created || f.deleted) && (
                  <Chip
                    label={f.deleted ? 'deleted' : 'new file'}
                    size="small"
                    sx={{
                      height: 17,
                      fontSize: '0.6rem',
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      bgcolor: f.deleted ? `${c.status.error}25` : `${c.status.success}25`,
                      color: f.deleted ? c.status.error : c.status.success,
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
            {applying
              ? 'Converting…'
              : `Convert to ${target} (${files.length} file${files.length === 1 ? '' : 's'})`}
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
  const [previewing, setPreviewing] = React.useState<Direction | null>(null);
  // Only `mixed` is a problem. Both settled variants are fine places for a workspace to be, so the
  // card colours off "is it in one of them" rather than off a passing count that treats the
  // template as correct and everything else as damage.
  const settled = app.variant === 'template' || app.variant === 'terminal';
  // A mixed app is described by how its checks split across the two variants, not by a passing
  // count: "3/6 passing" implies six were meant to pass, which is only true of one of the variants.
  const graded = app.checks.filter((k) => k.side !== 'na').length;
  const onTemplate = app.checks.filter((k) => k.side === 'template').length;
  const variantColor =
    app.variant === 'mixed'
      ? c.status.error
      : app.variant === 'unknown'
        ? c.text.muted
        : c.status.success;

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
        {/* Only `mixed` earns the X. `unknown` means there was no backend to grade, which is a
            shrug, not a failure, and a red cancel icon read as a broken app. */}
        {settled ? (
          <CheckCircleIcon sx={{ fontSize: 20, color: c.status.success }} />
        ) : app.variant === 'mixed' ? (
          <CancelIcon sx={{ fontSize: 20, color: variantColor }} />
        ) : (
          <RemoveCircleOutlineIcon sx={{ fontSize: 20, color: variantColor }} />
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
            {/* Neither variant is missing these, so no conversion reaches them. Without this the
                app reads as a settled variant while lacking a fix both variants carry. */}
            {app.shared_missing.length > 0 && (
              <Tooltip
                title={`Fails ${app.shared_missing.join(', ')}, which both variants pass. Converting will not fix this.`}
              >
                <Chip
                  label={`${app.shared_missing.length} behind both`}
                  size="small"
                  sx={{
                    height: 19,
                    fontSize: '0.65rem',
                    fontWeight: 600,
                    bgcolor: `${c.status.error}1A`,
                    color: c.status.error,
                  }}
                />
              </Tooltip>
            )}
          </Box>
          <Typography sx={{ fontSize: '0.72rem', color: c.text.ghost, fontFamily: c.font.mono }}>
            {app.id}
          </Typography>
        </Box>

        <Box sx={{ width: 104, flexShrink: 0 }}>
          <Typography
            sx={{ fontSize: '0.8rem', fontWeight: 600, color: variantColor, textAlign: 'right' }}
          >
            {VARIANT_LABEL[app.variant]}
          </Typography>
          <Typography sx={{ fontSize: '0.68rem', color: c.text.ghost, textAlign: 'right' }}>
            {app.variant === 'mixed'
              ? `${onTemplate}/${graded} template-side`
              : app.variant === 'unknown'
                ? 'no backend to grade'
                : 'variant'}
          </Typography>
        </Box>

        {/* Both directions are always offered, and the one the workspace is already in is disabled
            rather than hidden. A Template app previously showed no button at all, which made the
            template look like the only destination when it is just the one it happens to be in. */}
        <Box sx={{ display: 'flex', gap: 0.75, flexShrink: 0 }} onClick={(e) => e.stopPropagation()}>
          {(['harden', 'revert'] as Direction[]).map((dir) => {
            const dest = DIRECTION_TARGET[dir];
            const here = app.variant === dest;
            // The variants differ in backend/run.sh, so there is nothing to convert without one.
            // Offering the button anyway invited a click whose whole plan would be empty.
            const nothingToConvert = !app.has_backend;
            return (
              <Tooltip
                key={dir}
                title={
                  nothingToConvert
                    ? 'This app has no backend, so there are no variant scripts to convert.'
                    : here
                      ? `Already on ${VARIANT_LABEL[dest]}`
                      : `Preview the exact patch that converts this app to ${VARIANT_LABEL[dest]}`
                }
              >
                {/* span so the tooltip still fires while the button is disabled */}
                <Box component="span">
                  <Button
                    onClick={() => setPreviewing(dir)}
                    disabled={here || nothingToConvert}
                    startIcon={<AutoFixHighIcon sx={{ fontSize: 15 }} />}
                    size="small"
                    sx={{
                      textTransform: 'none',
                      borderRadius: 999,
                      px: 1.5,
                      fontSize: '0.78rem',
                      color: c.accent.primary,
                      border: `1px solid ${c.accent.primary}40`,
                      '&:hover': { bgcolor: `${c.accent.primary}12`, borderColor: c.accent.primary },
                      '&.Mui-disabled': { color: c.text.ghost, borderColor: c.border.subtle },
                    }}
                  >
                    {VARIANT_LABEL[dest]}
                  </Button>
                </Box>
              </Tooltip>
            );
          })}
        </Box>

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
        <FixPreview
          app={app}
          direction={previewing}
          onClose={() => setPreviewing(null)}
          onApplied={onFixed}
        />
      )}

      <Collapse in={open} unmountOnExit>
        <Box sx={{ px: 2.5, pb: 2.5, pt: 0.5, display: 'flex', flexDirection: 'column', gap: 1.25 }}>
          {app.checks.map((chk) => {
            const row = SIDE_ROW[chk.side];
            const tint =
              row.tone === 'bad'
                ? c.status.error
                : row.tone === 'good'
                  ? c.status.success
                  : c.text.ghost;
            return (
              <Box
                key={chk.id}
                sx={{
                  display: 'flex',
                  gap: 1.25,
                  p: 1.5,
                  borderRadius: `${c.radius.md}px`,
                  bgcolor:
                    row.tone === 'bad'
                      ? c.status.errorBg
                      : row.tone === 'good'
                        ? c.status.successBg
                        : `${c.text.primary}08`,
                }}
              >
                {row.tone === 'good' ? (
                  <CheckCircleIcon sx={{ fontSize: 17, color: tint, mt: '2px' }} />
                ) : row.tone === 'bad' ? (
                  <CancelIcon sx={{ fontSize: 17, color: tint, mt: '2px' }} />
                ) : (
                  <RemoveCircleOutlineIcon sx={{ fontSize: 17, color: tint, mt: '2px' }} />
                )}
                <Box sx={{ flex: 1 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                    <Typography sx={{ fontSize: '0.85rem', fontWeight: 550, color: c.text.primary }}>
                      {chk.label}
                    </Typography>
                    {/* Names the variant this file is written in. Without it the icon alone is the
                        ambiguity the page had before: green meant "template" but read as "correct". */}
                    <Tooltip
                      title={
                        chk.side === 'neither'
                          ? 'This file matches neither variant, so no conversion will settle it.'
                          : chk.side === 'na'
                            ? 'This check does not apply to this app.'
                            : `This file is written the ${row.label} way.`
                      }
                    >
                      <Chip
                        label={row.label}
                        size="small"
                        sx={{
                          height: 17,
                          fontSize: '0.6rem',
                          fontWeight: 700,
                          textTransform: 'uppercase',
                          bgcolor: `${tint}1F`,
                          color: tint,
                        }}
                      />
                    </Tooltip>
                    {chk.side === 'neither' && (
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
                  {/* Only shown for `neither`. A Terminal-side row is not waiting to be fixed; it is
                      already somewhere, and telling the user how to leave it is not a repair. */}
                  {chk.side === 'neither' && (
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
            );
          })}
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

  // Reports the variant each app is in, and details only the mixed ones. Listing every failing
  // check made a settled Terminal app look broken when it is simply not the template.
  const copyReport = () => {
    if (!data) return;
    const lines = data.apps.map((a) => {
      const head = `${a.name} (${a.id}) — ${VARIANT_LABEL[a.variant]}`;
      if (a.variant !== 'mixed') return head;
      // Every graded check, each labelled with the variant it matches. Listing only the failures
      // described a mixed app as a pile of bugs instead of a split, which is what it actually is.
      return `${head}\n${a.checks
        .filter((k) => k.side !== 'na')
        .map((k) => `    [${SIDE_ROW[k.side].label}] ${k.label}: ${k.detail}`)
        .join('\n')}`;
    });
    const v = data.variants;
    navigator.clipboard.writeText(
      `Drift scan — ${data.total} workspaces: ${v.template} template, ${v.terminal} terminal, ` +
        `${v.mixed} mixed, ${v.unknown} unknown\n\n${lines.join('\n\n')}`,
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
            Sorts every app workspace in this install into one of two variants. Neither is more
            correct than the other, and you can convert an app either way; only <em>Mixed</em> is a
            problem, because a half-applied swap sits in neither. Read-only until you apply: the
            scan reads text files and stats one marker, and never runs anything.
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
            <Stat value={data.variants.template} label="on Template" color={c.status.success} />
            <Stat value={data.variants.terminal} label="on Terminal" color={c.status.success} />
            <Stat
              value={data.variants.mixed}
              label="mixed — neither variant"
              color={data.variants.mixed > 0 ? c.status.error : c.text.secondary}
            />
            {/* Backendless apps land here and are a normal fifth of this install, so omitting the
                tile left the four counts failing to add up to the total. */}
            <Stat
              value={data.variants.unknown}
              label="no backend to grade"
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
