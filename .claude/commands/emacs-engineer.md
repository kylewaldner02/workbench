# Emacs Lisp Engineering

Use when writing, debugging, or modifying Emacs Lisp code in this project (elisp/workbench.el).

## Critical Gotchas

### `let` vs `let*`
`let` evaluates ALL init forms before binding. If one binding depends on another, use `let*`:
```elisp
;; BUG: call-process runs with OLD default-directory
(let ((default-directory dir)
      (exit-code (call-process "git" nil t nil "status")))
  ...)

;; FIX: let* ensures default-directory is set before call-process
(let* ((default-directory dir)
       (exit-code (call-process "git" nil t nil "status")))
  ...)
```

### `cl-return-from` requires `cl-defun`
`cl-return-from` only works inside `cl-defun` (which creates an implicit block), NOT inside regular `defun`. Use `when`/`unless` control flow or `catch`/`throw` instead:
```elisp
;; BUG: no-catch error at runtime
(defun foo () (cl-return-from foo nil))

;; FIX option 1: use cl-defun
(cl-defun foo () (cl-return-from foo nil))

;; FIX option 2: restructure with when/unless (preferred for simple cases)
(defun foo () (unless condition (do-stuff)))
```

### `defvar` doesn't re-evaluate
`defvar` only sets the value if the variable is unbound. When reloading a file during development, keymaps and other `defvar` values WON'T update. Use `defvar` + `setq` for keymaps:
```elisp
(defvar my-mode-map nil)
(setq my-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "g") #'my-command)
    map))
```

### `default-directory` needs trailing slash
Emacs requires `default-directory` to end with `/`. Use `file-name-as-directory`:
```elisp
(let* ((default-directory (file-name-as-directory (expand-file-name dir)))
       ...)
```

### Path comparison
Always normalize paths with `expand-file-name` before comparing. Paths from different sources (git output, JSON files, user input) may differ in trailing slashes or relative components.

## Async Patterns

### External commands → `make-process` + sentinel
Never block the UI with synchronous `call-process` for slow operations. Use `make-process`:
```elisp
(make-process
 :name "my-process"
 :buffer output-buf
 :command '("bash" "-c" "...")
 :sentinel (lambda (proc _event)
             (when (eq (process-status proc) 'exit)
               (unwind-protect
                   (when (= (process-exit-status proc) 0)
                     ;; parse output-buf, update state, re-render
                     )
                 (kill-buffer output-buf)))))
```

### Batch shell work into one subprocess
Instead of N sequential `call-process` calls, build a single bash script that does all the work and outputs structured (tab-delimited) results. Parse in the sentinel.

### Incremental work → `run-with-idle-timer`
For CPU-bound elisp work (like parsing many files), process one item per idle timer tick:
```elisp
(defun process-next (remaining)
  (when remaining
    (run-with-idle-timer 0.1 nil
      (lambda ()
        (do-one-item (car remaining))
        (process-next (cdr remaining))))))
```

### Guard against concurrent refreshes
Use a flag to prevent overlapping async operations:
```elisp
(defvar my--in-progress nil)
(cl-defun my-refresh ()
  (when my--in-progress (cl-return-from my-refresh))
  (setq my--in-progress t)
  (make-process ... :sentinel (lambda (...) (unwind-protect ... (setq my--in-progress nil)))))
```

## Buffer Rendering (special-mode pattern)

- Derive from `special-mode` (read-only, no self-insert)
- Use `inhibit-read-only` + `erase-buffer` + re-insert for full redraws
- Store data on lines via `put-text-property` with a custom property (e.g. `'workbench-node`)
- Read it back with `get-text-property` at `(line-beginning-position)`
- Save/restore cursor position by line number across redraws
- Use `hl-line-mode` for visual cursor

## macOS Terminal Integration

- `open -g -a Terminal file.command` — opens in background (no focus steal)
- `open -a Terminal file.command` — opens and brings Terminal to front
- For tabs: requires macOS "Prefer tabs when opening documents: Always"
- `.command` files: temp file with `#!/bin/bash`, `chmod 755`, opened via `open`

## Customization Patterns

- Use `defcustom` for user config, never JSON config files
- For overridable behavior, use function-valued defcustoms:
  ```elisp
  (defcustom my-open-function #'my-open-default
    "Function called with one arg: directory path."
    :type 'function)
  ```
- Then dispatch: `(funcall my-open-function dir)`
