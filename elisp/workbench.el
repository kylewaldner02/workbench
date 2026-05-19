;;; workbench.el --- Git worktree manager with tool launchers -*- lexical-binding: t -*-

;; Author: Kyle Waldner
;; Version: 0.1.0
;; Package-Requires: ((emacs "28.1") (transient "0.4.0"))
;; Keywords: vc, tools, convenience

;;; Commentary:
;;
;; A worktree manager with integrated tool launchers for Claude Code,
;; IDEs, and VCS clients.  Shares state with the workbench CLI via
;; ~/.workbench/.
;;
;; Usage: M-x workbench

;;; Code:

(require 'json)
(require 'cl-lib)
(require 'transient)

;; ══════════════════════════════════════════════════════════════════
;; Customization
;; ══════════════════════════════════════════════════════════════════

(defgroup workbench nil
  "Git worktree manager with integrated tool launchers."
  :group 'tools
  :group 'vc)

(defcustom workbench-state-directory (expand-file-name "~/.workbench/")
  "Directory for workbench state files.
Shared with the workbench CLI."
  :group 'workbench
  :type 'directory)

(defcustom workbench-ide "intellij"
  "IDE to launch.  One of \"intellij\" or \"vscode\"."
  :group 'workbench
  :type '(choice (const "intellij") (const "vscode")))

(defcustom workbench-vcs-client "emacs-magit"
  "VCS client to launch.
One of \"emacs-magit\", \"emacs-open\", or \"lazygit\"."
  :group 'workbench
  :type '(choice (const "emacs-magit") (const "emacs-open") (const "lazygit")))

(defcustom workbench-terminal "terminal-app"
  "Terminal emulator.  One of \"terminal-app\" or \"iterm2\"."
  :group 'workbench
  :type '(choice (const "terminal-app") (const "iterm2")))

(defcustom workbench-refresh-interval 5
  "Seconds between auto-refresh of the workbench buffer."
  :group 'workbench
  :type 'integer)

(defcustom workbench-branch-strip-prefixes nil
  "List of branch name prefixes to strip in the main display.
For example, (\"kylewaldner/\" \"kyle/\") would display
\"kylewaldner/my-feature\" as \"my-feature\"."
  :group 'workbench
  :type '(repeat string))

;; Tool launcher function overrides
;; Each takes a single DIR argument (the worktree path).

(defcustom workbench-open-git-function #'workbench-open-git-default
  "Function to open a git client.  Called with one arg: worktree directory."
  :group 'workbench
  :type 'function)

(defcustom workbench-open-ide-function #'workbench-open-ide-default
  "Function to open an IDE.  Called with one arg: worktree directory."
  :group 'workbench
  :type 'function)

(defcustom workbench-open-terminal-function #'workbench-open-terminal-default
  "Function to open a terminal.  Called with one arg: worktree directory."
  :group 'workbench
  :type 'function)

(defcustom workbench-open-claude-function #'workbench-open-claude-default
  "Function to open Claude.  Called with one arg: worktree directory."
  :group 'workbench
  :type 'function)

(defcustom workbench-new-session-function #'workbench-new-session-default
  "Function to open a new Claude session.  Called with one arg: worktree directory."
  :group 'workbench
  :type 'function)

(defcustom workbench-resume-session-function #'workbench-resume-session-default
  "Function to resume a Claude session.
Called with two args: worktree directory and session plist."
  :group 'workbench
  :type 'function)

(defcustom workbench-fork-session-function #'workbench-fork-session-default
  "Function to fork a Claude session.
Called with two args: worktree directory and session plist."
  :group 'workbench
  :type 'function)

;; ══════════════════════════════════════════════════════════════════
;; Faces
;; ══════════════════════════════════════════════════════════════════

(defface workbench-project-face
  '((t :weight bold))
  "Face for project names."
  :group 'workbench)

(defface workbench-branch-face
  '((t :weight bold))
  "Face for branch names."
  :group 'workbench)

(defface workbench-repo-face
  '((t :foreground "gray60"))
  "Face for repo names."
  :group 'workbench)

(defface workbench-clean-face
  '((t :foreground "gray60"))
  "Face for clean git status."
  :group 'workbench)

(defface workbench-dirty-face
  '((t :foreground "orange"))
  "Face for dirty git status."
  :group 'workbench)

(defface workbench-sessions-face
  '((t :foreground "green"))
  "Face for session count when > 0."
  :group 'workbench)

(defface workbench-no-sessions-face
  '((t :foreground "gray60"))
  "Face for no sessions."
  :group 'workbench)

(defface workbench-pr-face
  '((t :foreground "cyan"))
  "Face for PR numbers."
  :group 'workbench)

(defface workbench-dim-face
  '((t :foreground "gray60"))
  "Face for dim/secondary text."
  :group 'workbench)

(defface workbench-session-label-face
  '((t :foreground "gray80"))
  "Face for session labels."
  :group 'workbench)

(defface workbench-column-header-face
  '((t :foreground "gray50" :weight bold))
  "Face for column headers."
  :group 'workbench)

(defface workbench-cursor-face
  '((t :inherit highlight))
  "Face for the current line cursor."
  :group 'workbench)

;; ══════════════════════════════════════════════════════════════════
;; Internal state
;; ══════════════════════════════════════════════════════════════════

(defvar workbench--refresh-timer nil)
(defvar workbench--pr-cache nil "Alist of (branch . pr-plist).")
(defvar workbench--fold-cache nil "Hash table of fold states (buffer-local, not persisted).")
(defvar workbench--wt-cache nil "Cached list of all worktree plists.")
(defvar workbench--extras-cache nil "Hash table of path -> (status sessions last-commit).")
(defvar workbench--projects-cache nil "Cached list of project alists.")

;; Column widths — fixed columns, branch expands to fill remaining space
;; Each width includes 2 chars of trailing gap
(defconst workbench--col-repo 28)
(defconst workbench--col-status 14)
(defconst workbench--col-sessions 16)
(defconst workbench--col-pr 8)
(defconst workbench--col-commit 16)
(defconst workbench--col-indent 6)

(defun workbench--col-branch ()
  "Compute branch column width to fill available space."
  (let* ((fixed (+ workbench--col-indent
                   workbench--col-repo
                   workbench--col-status
                   workbench--col-sessions
                   workbench--col-pr
                   workbench--col-commit))
         (available (- (window-width) fixed)))
    (max 20 available)))

;; ══════════════════════════════════════════════════════════════════
;; State I/O — reads/writes ~/.workbench/local-state/
;; ══════════════════════════════════════════════════════════════════

(defun workbench--state-dir ()
  "Return the local-state directory path, ensuring it exists."
  (let ((dir (expand-file-name "local-state/" workbench-state-directory)))
    (make-directory dir t)
    dir))

(defun workbench--read-json (filename)
  "Read JSON from FILENAME in the state directory.  Return nil on error."
  (let ((path (expand-file-name filename (workbench--state-dir))))
    (when (file-exists-p path)
      (condition-case nil
          (json-read-file path)
        (error nil)))))

(defun workbench--write-json (filename data)
  "Write DATA as JSON to FILENAME in the state directory."
  (let ((path (expand-file-name filename (workbench--state-dir))))
    (with-temp-file path
      (insert (json-encode data))
      (json-pretty-print-buffer)
      (goto-char (point-max))
      (insert "\n"))))

(defun workbench--load-repos ()
  "Return list of repo path strings."
  (let ((data (workbench--read-json "repos.json")))
    (when data
      (append (cdr (assq 'repos data)) nil))))

(defun workbench--save-repos (repos)
  "Save REPOS list to disk."
  (workbench--write-json "repos.json" `((repos . ,(vconcat (sort (delete-dups repos) #'string<))))))

(defun workbench--add-repo (path)
  "Add PATH to known repos."
  (let* ((resolved (expand-file-name path))
         (repos (workbench--load-repos)))
    (unless (member resolved repos)
      (push resolved repos)
      (workbench--save-repos repos))))

(defun workbench--load-projects ()
  "Return list of project alists (non-archived only)."
  (let ((data (workbench--read-json "projects.json")))
    (when data
      (cl-remove-if (lambda (p) (eq (cdr (assq 'archived p)) t))
                     (append (cdr (assq 'projects data)) nil)))))

(defun workbench--load-all-projects ()
  "Return all projects including archived."
  (let ((data (workbench--read-json "projects.json")))
    (when data
      (append (cdr (assq 'projects data)) nil))))

(defun workbench--load-archived-projects ()
  "Return list of archived project alists."
  (let ((data (workbench--read-json "projects.json")))
    (when data
      (cl-remove-if-not (lambda (p) (eq (cdr (assq 'archived p)) t))
                         (append (cdr (assq 'projects data)) nil)))))

(defun workbench--save-all-projects (projects)
  "Save full PROJECTS list (active + archived)."
  (workbench--write-json "projects.json" `((projects . ,(vconcat projects)))))

(defun workbench--project-name (project)
  "Get name from PROJECT alist."
  (cdr (assq 'name project)))

(defun workbench--project-worktrees (project)
  "Get worktrees vector from PROJECT alist."
  (let ((wts (cdr (assq 'worktrees project))))
    (if wts (append wts nil) nil)))

(defun workbench--create-project (name)
  "Create a new project with NAME."
  (let ((all (workbench--load-all-projects)))
    (when (cl-find name all :key #'workbench--project-name :test #'equal)
      (user-error "Project '%s' already exists" name))
    (push `((name . ,name) (worktrees . [])) all)
    (workbench--save-all-projects (nreverse all))))

(defun workbench--archive-project (name)
  "Archive project NAME."
  (let ((all (workbench--load-all-projects)))
    (dolist (p all)
      (when (equal (workbench--project-name p) name)
        (if (assq 'archived p)
            (setcdr (assq 'archived p) t)
          (nconc p (list (cons 'archived t))))))
    (workbench--save-all-projects all)))

(defun workbench--unarchive-project (name)
  "Unarchive project NAME."
  (let ((all (workbench--load-all-projects)))
    (dolist (p all)
      (when (equal (workbench--project-name p) name)
        (let ((cell (assq 'archived p)))
          (when cell (setcdr cell :json-false)))))
    (workbench--save-all-projects all)))

(defun workbench--delete-project (name)
  "Delete project NAME permanently."
  (let ((all (workbench--load-all-projects)))
    (workbench--save-all-projects
     (cl-remove-if (lambda (p) (equal (workbench--project-name p) name)) all))))

(defun workbench--add-worktree-to-project (project-name repo branch wt-path)
  "Add worktree to PROJECT-NAME."
  (let ((all (workbench--load-all-projects)))
    (dolist (p all)
      (when (equal (workbench--project-name p) project-name)
        (let* ((wts (workbench--project-worktrees p))
               (already (cl-find wt-path wts
                                 :key (lambda (w) (cdr (assq 'worktree_path w)))
                                 :test #'equal)))
          (unless already
            (let ((new-wt `((repo . ,repo) (branch . ,branch) (worktree_path . ,wt-path))))
              (setcdr (assq 'worktrees p)
                      (vconcat (cdr (assq 'worktrees p)) (vector new-wt))))))))
    (workbench--save-all-projects all)))

(defun workbench--remove-worktree-from-project (project-name wt-path)
  "Remove worktree at WT-PATH from PROJECT-NAME."
  (let ((all (workbench--load-all-projects)))
    (dolist (p all)
      (when (equal (workbench--project-name p) project-name)
        (let ((wts (workbench--project-worktrees p)))
          (setcdr (assq 'worktrees p)
                  (vconcat (cl-remove-if
                            (lambda (w) (equal (cdr (assq 'worktree_path w)) wt-path))
                            wts))))))
    (workbench--save-all-projects all)))

(defun workbench--find-project-for-worktree (wt-path)
  "Return project name that contains WT-PATH, or nil."
  (cl-loop for p in (workbench--load-projects)
           when (cl-find wt-path (workbench--project-worktrees p)
                         :key (lambda (w) (cdr (assq 'worktree_path w)))
                         :test #'equal)
           return (workbench--project-name p)))

(defun workbench--fold-get (key default)
  "Get fold state for KEY with DEFAULT."
  (unless workbench--fold-cache
    (setq workbench--fold-cache (make-hash-table :test 'equal)))
  (gethash key workbench--fold-cache default))

(defun workbench--fold-set (key expanded)
  "Set fold state for KEY to EXPANDED."
  (unless workbench--fold-cache
    (setq workbench--fold-cache (make-hash-table :test 'equal)))
  (puthash key expanded workbench--fold-cache))

(defun workbench--load-hidden-worktrees ()
  "Return set (list) of hidden worktree paths."
  (let ((data (workbench--read-json "hidden_worktrees.json")))
    (when data
      (append (cdr (assq 'hidden data)) nil))))

(defun workbench--hide-worktree (wt-path)
  "Hide worktree at WT-PATH."
  (let ((hidden (workbench--load-hidden-worktrees)))
    (unless (member wt-path hidden)
      (push wt-path hidden))
    (workbench--write-json "hidden_worktrees.json"
                           `((hidden . ,(vconcat (sort hidden #'string<)))))))

;; ══════════════════════════════════════════════════════════════════
;; Git operations
;; ══════════════════════════════════════════════════════════════════

(defun workbench--git-output (dir &rest args)
  "Run git with ARGS in DIR, return stdout string or nil on failure."
  (let ((dir (file-name-as-directory (expand-file-name dir))))
    (when (file-directory-p dir)
      (with-temp-buffer
        (let* ((default-directory dir)
               (exit-code (apply #'call-process "git" nil t nil args)))
          (when (= exit-code 0)
            (string-trim-right (buffer-string))))))))

(defun workbench--git-status (dir)
  "Return short git status string for DIR."
  (let ((output (workbench--git-output dir "status" "--porcelain")))
    (cond
     ((null output) "error")
     ((string-empty-p output) "clean")
     (t (let ((n (length (split-string output "\n" t))))
          (if (= n 1) "1 change" (format "%d changes" n)))))))

(defun workbench--last-commit-time (dir)
  "Return relative time of last commit in DIR."
  (or (workbench--git-output dir "log" "-1" "--format=%cr") "no commits"))

(defun workbench--has-unpushed-changes (dir branch)
  "Return non-nil if DIR/BRANCH has uncommitted or unpushed changes."
  (let ((status (workbench--git-output dir "status" "--porcelain")))
    (if (and status (not (string-empty-p status)))
        t
      (let ((log (workbench--git-output dir "log" (format "origin/%s..%s" branch branch) "--oneline")))
        (or (null log) (not (string-empty-p log)))))))

(defun workbench--list-worktrees-for-repo (repo-path)
  "Parse `git worktree list --porcelain` for REPO-PATH.
Returns list of plists (:path :branch :head :repo :bare)."
  (let ((output (workbench--git-output repo-path "worktree" "list" "--porcelain")))
    (when output
      (let ((entries nil)
            (current nil))
        (dolist (line (split-string output "\n"))
          (cond
           ((string-empty-p line)
            (when current
              (push (workbench--parse-wt-entry current repo-path) entries)
              (setq current nil)))
           ((string-prefix-p "worktree " line)
            (setq current (list (cons 'path (substring line 9)))))
           ((string-prefix-p "HEAD " line)
            (push (cons 'head (substring line 5)) current))
           ((string-prefix-p "branch " line)
            (push (cons 'branch (substring line 7)) current))
           ((string= line "bare")
            (push (cons 'bare t) current))
           ((string= line "detached")
            (push (cons 'detached t) current))))
        (when current
          (push (workbench--parse-wt-entry current repo-path) entries))
        (nreverse entries)))))

(defun workbench--parse-wt-entry (entry repo)
  "Parse an ENTRY alist into a worktree plist for REPO."
  (let* ((branch-ref (or (cdr (assq 'branch entry)) ""))
         (branch (if (string-prefix-p "refs/heads/" branch-ref)
                     (substring branch-ref 11)
                   (if (string-empty-p branch-ref) "(detached)" branch-ref))))
    (list :path (expand-file-name (cdr (assq 'path entry)))
          :branch branch
          :head (or (cdr (assq 'head entry)) "")
          :repo (expand-file-name repo)
          :bare (cdr (assq 'bare entry)))))

(defun workbench--list-all-worktrees ()
  "List all worktrees across known repos, excluding hidden and bare."
  (let ((repos (workbench--load-repos))
        (hidden (workbench--load-hidden-worktrees))
        (all nil))
    (dolist (repo repos)
      (when (file-directory-p repo)
        (dolist (wt (workbench--list-worktrees-for-repo repo))
          (unless (or (plist-get wt :bare)
                      (member (plist-get wt :path) hidden))
            (push wt all)))))
    (nreverse all)))

(defun workbench--repo-name (repo-path)
  "Return short name for REPO-PATH."
  (file-name-nondirectory (directory-file-name repo-path)))

(defun workbench--disambiguate-paths (paths)
  "Return alist of (display-name . full-path) with minimal unique suffixes.
Paths under ~ are shortened to use ~.  When basenames collide,
parent dirs are added until all names are unique."
  (let* ((home (file-name-as-directory (expand-file-name "~")))
         (entries (mapcar
                   (lambda (p)
                     (let* ((exp (directory-file-name (expand-file-name p)))
                            (parts (nreverse (split-string exp "/" t))))
                       (list :path p :full exp :parts parts :depth 1)))
                   paths)))
    ;; Increase depth for colliding names until unique
    (let ((max-iter 20))
      (while (> max-iter 0)
        (setq max-iter (1- max-iter))
        (let ((name-counts (make-hash-table :test 'equal)))
          (dolist (e entries)
            (let ((name (workbench--build-suffix (plist-get e :parts) (plist-get e :depth))))
              (puthash name (1+ (or (gethash name name-counts) 0)) name-counts)))
          (let ((any-dup nil))
            (dolist (e entries)
              (let ((name (workbench--build-suffix (plist-get e :parts) (plist-get e :depth))))
                (when (> (gethash name name-counts) 1)
                  (plist-put e :depth (min (1+ (plist-get e :depth)) (length (plist-get e :parts))))
                  (setq any-dup t))))
            (unless any-dup (setq max-iter 0))))))
    ;; Build display names, only add ~ prefix when disambiguation needed it
    (mapcar (lambda (e)
              (let* ((full (plist-get e :full))
                     (suffix (workbench--build-suffix (plist-get e :parts) (plist-get e :depth)))
                     (depth (plist-get e :depth))
                     (total-parts (length (plist-get e :parts)))
                     ;; Only add ~ when we've swum up past ~ boundary
                     (display (if (and (> depth 1)
                                       (string-prefix-p home full)
                                       (= depth total-parts))
                                  (concat "~/" suffix)
                                suffix)))
                (cons display (plist-get e :path))))
            entries)))

(defun workbench--build-suffix (reversed-parts depth)
  "Build a path suffix from REVERSED-PARTS with DEPTH components."
  (let ((parts (cl-subseq reversed-parts 0 (min depth (length reversed-parts)))))
    (mapconcat #'identity (nreverse parts) "/")))

(defun workbench--is-main-worktree (wt)
  "Return non-nil if WT is the repo's main worktree."
  (string= (expand-file-name (plist-get wt :path))
           (expand-file-name (plist-get wt :repo))))

(defun workbench--create-worktree (repo-path branch)
  "Create a new worktree for BRANCH in REPO-PATH.  Return the worktree plist."
  (let* ((wt-dir (expand-file-name ".worktrees/" repo-path))
         (wt-path (expand-file-name branch wt-dir)))
    (make-directory wt-dir t)
    (let ((result (workbench--git-output repo-path "worktree" "add" wt-path "-b" branch "HEAD")))
      (unless result
        ;; Branch might exist already
        (let ((result2 (workbench--git-output repo-path "worktree" "add" wt-path branch)))
          (unless result2
            (user-error "Failed to create worktree for %s" branch)))))
    ;; Find and return the new worktree
    (or (cl-find wt-path (workbench--list-worktrees-for-repo repo-path)
                 :key (lambda (w) (plist-get w :path)) :test #'equal)
        (list :path wt-path :branch branch :head "unknown" :repo repo-path))))

(defun workbench--remove-worktree (wt-path)
  "Remove the worktree at WT-PATH."
  (let ((result (with-temp-buffer
                  (call-process "git" nil t nil "worktree" "remove" wt-path "--force")
                  (buffer-string))))
    (when (string-match-p "fatal" result)
      (user-error "Failed to remove worktree: %s" (string-trim result)))))

;; ══════════════════════════════════════════════════════════════════
;; Claude Code sessions
;; ══════════════════════════════════════════════════════════════════

(defun workbench--claude-projects-dir ()
  "Return Claude Code projects directory."
  (expand-file-name "~/.claude/projects/"))

(defun workbench--claude-project-dir (wt-path)
  "Find the Claude project directory for WT-PATH."
  (let* ((resolved (expand-file-name wt-path))
         (encoded (replace-regexp-in-string "[/.]" "-" resolved))
         (candidate (expand-file-name encoded (workbench--claude-projects-dir))))
    (when (file-directory-p candidate)
      candidate)))

(defun workbench--claude-list-sessions (wt-path)
  "List Claude sessions for WT-PATH.
Returns list of plists (:id :label :last-active)."
  (let ((dir (workbench--claude-project-dir wt-path)))
    (when dir
      (let ((files (directory-files dir t "\\.jsonl$"))
            (sessions nil))
        ;; Sort by mtime, newest first
        (setq files (sort files (lambda (a b)
                                  (time-less-p (file-attribute-modification-time (file-attributes b))
                                               (file-attribute-modification-time (file-attributes a))))))
        (dolist (f files)
          (let ((session (workbench--parse-claude-session f)))
            (when session (push session sessions))))
        (nreverse sessions)))))

(defun workbench--parse-claude-session (path)
  "Parse a Claude session JSONL file at PATH.  Return plist or nil."
  (condition-case nil
      (let ((label (file-name-sans-extension (file-name-nondirectory path)))
            (first-user-msg nil)
            (last-ts nil))
        (with-temp-buffer
          (insert-file-contents path)
          (goto-char (point-min))
          (while (not (eobp))
            (let ((line (buffer-substring-no-properties (line-beginning-position) (line-end-position))))
              (unless (string-empty-p line)
                (condition-case nil
                    (let ((entry (json-read-from-string line)))
                      ;; Extract first user message
                      (unless first-user-msg
                        (let* ((msg (cdr (assq 'message entry)))
                               (type (cdr (assq 'type entry)))
                               (role (and msg (cdr (assq 'role msg)))))
                          (when (or (equal type "user") (equal role "user"))
                            (let ((content (or (and msg (cdr (assq 'content msg)))
                                               (cdr (assq 'content entry)))))
                              (cond
                               ((vectorp content)
                                (cl-loop for block across content
                                         when (and (listp block) (equal (cdr (assq 'type block)) "text"))
                                         do (setq first-user-msg (substring (cdr (assq 'text block)) 0
                                                                            (min 80 (length (cdr (assq 'text block))))))
                                         and return nil))
                               ((stringp content)
                                (setq first-user-msg (substring content 0 (min 80 (length content))))))))))
                      ;; Track timestamp
                      (let ((ts (cdr (assq 'timestamp entry))))
                        (when (stringp ts) (setq last-ts ts))))
                  (error nil))))
            (forward-line 1)))
        (when first-user-msg
          (setq label (replace-regexp-in-string "\\s-+" " " (string-trim first-user-msg))))
        (list :id (file-name-sans-extension (file-name-nondirectory path))
              :label (if (> (length label) 80) (substring label 0 80) label)
              :last-active (workbench--relative-time last-ts)))
    (error nil)))

(defun workbench--relative-time (iso-timestamp)
  "Convert ISO-TIMESTAMP to a relative time string."
  (if (null iso-timestamp) "unknown"
    (condition-case nil
        (let* ((time (date-to-time iso-timestamp))
               (seconds (float-time (time-subtract (current-time) time))))
          (cond
           ((< seconds 60) "just now")
           ((< seconds 3600) (format "%dm ago" (floor seconds 60)))
           ((< seconds 86400) (format "%dh ago" (floor seconds 3600)))
           (t (format "%dd ago" (floor seconds 86400)))))
      (error "unknown"))))

;; ══════════════════════════════════════════════════════════════════
;; PR operations (via gh CLI)
;; ══════════════════════════════════════════════════════════════════

(defun workbench--list-prs ()
  "Fetch open PRs via `gh pr list`.  Return alist of (branch . plist)."
  (condition-case nil
      (with-temp-buffer
        (let ((exit-code (call-process "gh" nil t nil
                                       "pr" "list" "--json"
                                       "number,url,state,title,headRefName"
                                       "--limit" "100")))
          (when (= exit-code 0)
            (let ((data (json-read-from-string (buffer-string)))
                  result)
              (cl-loop for item across data
                       do (push (cons (cdr (assq 'headRefName item))
                                      (list :number (cdr (assq 'number item))
                                            :url (cdr (assq 'url item))
                                            :state (cdr (assq 'state item))
                                            :title (cdr (assq 'title item))))
                                result))
              result))))
    (error nil)))

(defun workbench--create-pr (branch base dir)
  "Create a PR for BRANCH against BASE.  DIR must be inside the repo.
Return PR plist."
  (let ((default-directory (file-name-as-directory (expand-file-name dir))))
    (with-temp-buffer
      (let ((exit-code (call-process "gh" nil t nil
                                     "pr" "create" "--head" branch "--base" base "--fill")))
        (unless (= exit-code 0)
          (user-error "Failed to create PR: %s" (string-trim (buffer-string))))))
    ;; Fetch the created PR
    (with-temp-buffer
      (let ((exit-code (call-process "gh" nil t nil
                                     "pr" "view" branch "--json" "number,url,state,title")))
        (when (= exit-code 0)
          (let ((data (json-read-from-string (buffer-string))))
            (list :number (cdr (assq 'number data))
                  :url (cdr (assq 'url data))
                  :state (cdr (assq 'state data))
                  :title (cdr (assq 'title data)))))))))

(defun workbench--open-pr-in-browser (branch dir)
  "Open PR for BRANCH in browser.  DIR must be inside the repo."
  (let ((default-directory (file-name-as-directory (expand-file-name dir))))
    (call-process "gh" nil nil nil "pr" "view" branch "--web")))

;; ══════════════════════════════════════════════════════════════════
;; Tool launchers
;; ══════════════════════════════════════════════════════════════════

(defun workbench--open-terminal (dir)
  "Open a terminal at DIR using the configured terminal."
  (let ((dir (expand-file-name dir)))
    (pcase workbench-terminal
      ("terminal-app"
       (start-process "workbench-term" nil "open" "-a" "Terminal" dir))
      ("iterm2"
       (start-process "workbench-term" nil "open" "-a" "iTerm" dir)))))

(defun workbench--run-in-terminal (cmd cwd)
  "Run CMD (list of strings) in CWD using the configured terminal."
  (let ((cwd (expand-file-name cwd)))
    (pcase workbench-terminal
      ("terminal-app"
       (let* ((shell-cmd (mapconcat #'shell-quote-argument cmd " "))
              (script (make-temp-file "workbench-" nil ".command"
                                      (format "#!/bin/bash\ncd %s\nexec %s\n"
                                              (shell-quote-argument cwd) shell-cmd))))
         (set-file-modes script #o755)
         (start-process "workbench-cmd" nil "open" script)))
      ("iterm2"
       (let* ((shell-cmd (mapconcat #'shell-quote-argument cmd " "))
              (full-cmd (format "cd %s && exec %s" (shell-quote-argument cwd) shell-cmd))
              (apple-script (format "tell application \"iTerm\"\n  create window with default profile\n  tell current session of current window\n    write text %s\n  end tell\nend tell"
                                    (shell-quote-argument full-cmd))))
         (start-process "workbench-cmd" nil "osascript" "-e" apple-script))))))

(defun workbench--open-ide (dir)
  "Open IDE at DIR."
  (let ((dir (expand-file-name dir)))
    (pcase workbench-ide
      ("intellij" (start-process "workbench-ide" nil "idea" dir))
      ("vscode" (start-process "workbench-ide" nil "code" dir)))))

(defun workbench--open-vcs (dir)
  "Open VCS client at DIR."
  (let ((dir (expand-file-name dir)))
    (pcase workbench-vcs-client
      ("emacs-magit"
       (if (fboundp 'magit-status)
           (magit-status dir)
         (user-error "magit not available")))
      ("emacs-open"
       (dired dir))
      ("lazygit"
       (workbench--run-in-terminal '("lazygit") dir)))))

(defun workbench--claude-open-cmd ()
  "Return the command list to open a new Claude session."
  '("caffeinate" "-i" "claude"))

(defun workbench--claude-resume-cmd (session-id)
  "Return the command list to resume Claude SESSION-ID."
  (list "caffeinate" "-i" "claude" "--resume" session-id))

;; ══════════════════════════════════════════════════════════════════
;; Buffer rendering
;; ══════════════════════════════════════════════════════════════════

(defun workbench--strip-branch-prefix (branch)
  "Strip configured prefixes from BRANCH for display."
  (cl-loop for prefix in workbench-branch-strip-prefixes
           when (string-prefix-p prefix branch)
           return (substring branch (length prefix))
           finally return branch))

(defun workbench--pad (str width)
  "Pad or truncate STR to WIDTH."
  (if (>= (length str) width)
      (substring str 0 width)
    (concat str (make-string (- width (length str)) ?\s))))

(defun workbench--render-column-header ()
  "Return the column header line as a propertized string."
  (let ((col-branch (workbench--col-branch)))
    (concat (make-string workbench--col-indent ?\s)
            (propertize (workbench--pad "Branch" col-branch) 'face 'workbench-column-header-face)
            (propertize (workbench--pad "Repo" workbench--col-repo) 'face 'workbench-column-header-face)
            (propertize (workbench--pad "Status" workbench--col-status) 'face 'workbench-column-header-face)
            (propertize (workbench--pad "Sessions" workbench--col-sessions) 'face 'workbench-column-header-face)
            (propertize (workbench--pad "PR" workbench--col-pr) 'face 'workbench-column-header-face)
            (propertize "Last Commit" 'face 'workbench-column-header-face))))

(defun workbench--render-worktree-line (wt extras)
  "Render a worktree line for WT with cached EXTRAS."
  (let* ((full-branch (plist-get wt :branch))
         (branch (workbench--strip-branch-prefix full-branch))
         (repo (workbench--repo-name (plist-get wt :repo)))
         (status (plist-get extras :status))
         (sessions (plist-get extras :sessions))
         (session-count (length sessions))
         (session-str (cond ((= session-count 0) "no sessions")
                            ((= session-count 1) "1 session")
                            (t (format "%d sessions" session-count))))
         (pr-data (cdr (assoc full-branch workbench--pr-cache)))
         (pr-str (if pr-data (format "#%d" (plist-get pr-data :number)) "-"))
         (last-commit (plist-get extras :last-commit)))
    (let ((col-branch (workbench--col-branch)))
    (concat
     (propertize (workbench--pad branch col-branch) 'face 'workbench-branch-face)
     (propertize (workbench--pad repo workbench--col-repo) 'face 'workbench-repo-face)
     (propertize (workbench--pad status workbench--col-status)
                 'face (if (string= status "clean") 'workbench-clean-face 'workbench-dirty-face))
     (propertize (workbench--pad session-str workbench--col-sessions)
                 'face (if (> session-count 0) 'workbench-sessions-face 'workbench-no-sessions-face))
     (propertize (workbench--pad pr-str workbench--col-pr)
                 'face (if pr-data 'workbench-pr-face 'workbench-dim-face))
     (propertize last-commit 'face 'workbench-dim-face)))))

(defun workbench--render-session-line (session)
  "Render a session line for SESSION plist."
  (let* ((label (plist-get session :label))
         (truncated (if (> (length label) 60) (concat (substring label 0 58) "..") label))
         (last-active (plist-get session :last-active)))
    (concat "    "
            (propertize (workbench--pad truncated 64) 'face 'workbench-session-label-face)
            (propertize last-active 'face 'workbench-dim-face))))

(defun workbench-refresh ()
  "Refresh the workbench buffer asynchronously."
  (interactive)
  (let ((buf (get-buffer "*workbench*")))
    (when (and buf (buffer-live-p buf))
      (with-current-buffer buf
        (workbench--async-refresh t)))))

(defun workbench--quick-refresh ()
  "Lightweight async refresh for the timer — skips session parsing.
Only runs when the buffer is displayed on a non-iconified frame."
  (let ((buf (get-buffer "*workbench*")))
    (when (and buf (buffer-live-p buf)
               (get-buffer-window buf 'visible))
      (with-current-buffer buf
        (workbench--async-refresh nil)))))

(defvar workbench--refresh-in-progress nil)

(cl-defun workbench--async-refresh (&optional fetch-sessions)
  "Refresh data asynchronously.  FETCH-SESSIONS means parse Claude sessions too."
  (when workbench--refresh-in-progress
    (if fetch-sessions
        ;; Full refresh supersedes in-progress one — kill it
        (let ((proc (get-process "workbench-git-refresh")))
          (when (and proc (process-live-p proc))
            (delete-process proc))
          (setq workbench--refresh-in-progress nil))
      (cl-return-from workbench--async-refresh)))
  ;; Load projects from JSON (instant file read)
  (setq workbench--projects-cache (workbench--load-projects))
  ;; Render immediately with whatever cache we have
  (workbench--rerender)
  (when fetch-sessions
    (setq header-line-format " workbench — refreshing..."))
  ;; Run everything in one async shell process
  (let* ((repos (workbench--load-repos))
         (hidden (workbench--load-hidden-worktrees))
         (script (workbench--build-full-script repos))
         (buf (current-buffer))
         (do-sessions fetch-sessions)
         (hidden-list hidden)
         (output-buf (generate-new-buffer " *workbench-git-async*")))
    (setq workbench--refresh-in-progress t)
    (make-process
     :name "workbench-git-refresh"
     :buffer output-buf
     :command (list "bash" "-c" script)
     :sentinel
     (lambda (proc _event)
       (when (eq (process-status proc) 'exit)
         (unwind-protect
             (when (and (= (process-exit-status proc) 0)
                        (buffer-live-p buf))
               (let ((parsed (workbench--parse-full-output output-buf hidden-list)))
                 (with-current-buffer buf
                   (setq workbench--wt-cache (car parsed))
                   (let ((ht (or workbench--extras-cache (make-hash-table :test 'equal))))
                     (dolist (r (cdr parsed))
                       (let* ((path (car r))
                              (status (cadr r))
                              (last-commit (caddr r))
                              (old (gethash path ht))
                              (old-sessions (and old (plist-get old :sessions)))
                              (old-fetched (and old (plist-get old :sessions-fetched))))
                         (puthash path (list :status status
                                            :last-commit last-commit
                                            :sessions old-sessions
                                            :sessions-fetched old-fetched)
                                  ht)))
                     (setq workbench--extras-cache ht))
                   (workbench--rerender)
                   (when do-sessions
                     (workbench--fetch-prs-async)
                     (workbench--fetch-sessions-incrementally)))))
           (setq workbench--refresh-in-progress nil)
           (kill-buffer output-buf)))))))

(defun workbench--fetch-sessions-incrementally ()
  "Fetch Claude sessions for all worktrees via an async Python subprocess."
  (let ((buf (current-buffer))
        (paths (mapcar (lambda (wt) (plist-get wt :path))
                       (or workbench--wt-cache nil)))
        (output-buf (generate-new-buffer " *workbench-sessions*")))
    (make-process
     :name "workbench-sessions"
     :buffer output-buf
     :command (list "python3" "-c" (workbench--session-parser-script)
                    (workbench--claude-projects-dir)
                    (mapconcat #'identity paths "\n"))
     :sentinel
     (lambda (proc _event)
       (when (eq (process-status proc) 'exit)
         (unwind-protect
             (when (and (= (process-exit-status proc) 0)
                        (buffer-live-p buf))
               (let ((sessions-by-path (workbench--parse-sessions-output output-buf)))
                 (with-current-buffer buf
                   (when workbench--extras-cache
                     (maphash
                      (lambda (path extras)
                        (let ((sessions (cdr (assoc path sessions-by-path))))
                          (puthash path (plist-put (plist-put extras :sessions sessions)
                                                   :sessions-fetched t)
                                   workbench--extras-cache)))
                      workbench--extras-cache))
                   (workbench--rerender))))
           (kill-buffer output-buf)))))))

(defun workbench--session-parser-script ()
  "Return a Python script that parses Claude session JSONL files."
  "
import sys, os, json, glob
from datetime import datetime, timezone

projects_dir = sys.argv[1]
wt_paths = sys.argv[2].split('\\n') if len(sys.argv) > 2 and sys.argv[2] else []

def relative_time(iso_ts):
    try:
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = (datetime.now(timezone.utc) - dt).total_seconds()
        if delta < 60: return 'just now'
        if delta < 3600: return f'{int(delta//60)}m ago'
        if delta < 86400: return f'{int(delta//3600)}h ago'
        return f'{int(delta//86400)}d ago'
    except: return 'unknown'

def parse_session(path):
    label = os.path.splitext(os.path.basename(path))[0]
    first_msg = None
    last_ts = None
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    entry = json.loads(line)
                    if first_msg is None:
                        msg = entry.get('message', {})
                        if entry.get('type') == 'user' or (isinstance(msg, dict) and msg.get('role') == 'user'):
                            content = (msg.get('content') if isinstance(msg, dict) else None) or entry.get('content', '')
                            if isinstance(content, list):
                                for block in content:
                                    if isinstance(block, dict) and block.get('type') == 'text':
                                        first_msg = block['text'][:80]
                                        break
                            elif isinstance(content, str) and content.strip():
                                first_msg = content.strip()[:80]
                    ts = entry.get('timestamp')
                    if isinstance(ts, str): last_ts = ts
                except: pass
    except: return None
    if first_msg:
        label = ' '.join(first_msg.split())[:80]
    sid = os.path.splitext(os.path.basename(path))[0]
    return (sid, label, relative_time(last_ts) if last_ts else 'unknown')

for wt_path in wt_paths:
    if not wt_path: continue
    resolved = os.path.realpath(wt_path)
    encoded = resolved.replace('/', '-').replace('.', '-')
    proj_dir = os.path.join(projects_dir, encoded)
    if not os.path.isdir(proj_dir): continue
    files = sorted(glob.glob(os.path.join(proj_dir, '*.jsonl')),
                   key=lambda p: os.path.getmtime(p), reverse=True)
    for f in files:
        result = parse_session(f)
        if result:
            print(f'{wt_path}\\t{result[0]}\\t{result[1]}\\t{result[2]}')
")

(defun workbench--parse-sessions-output (output-buf)
  "Parse Python session output.  Returns alist of (path . session-list)."
  (let ((result nil))
    (with-current-buffer output-buf
      (goto-char (point-min))
      (while (not (eobp))
        (let ((line (buffer-substring-no-properties (line-beginning-position) (line-end-position))))
          (when (string-match "\\`\\([^\t]+\\)\t\\([^\t]+\\)\t\\([^\t]+\\)\t\\(.*\\)\\'" line)
            (let* ((path (match-string 1 line))
                   (sid (match-string 2 line))
                   (label (match-string 3 line))
                   (last-active (match-string 4 line))
                   (session (list :id sid :label label :last-active last-active))
                   (existing (assoc path result)))
              (if existing
                  (setcdr existing (append (cdr existing) (list session)))
                (push (cons path (list session)) result)))))
        (forward-line 1)))
    result))

(defun workbench--build-full-script (repos)
  "Build a bash script that lists worktrees and gets git status for each.
Output: WT\\tPATH\\tBRANCH\\tHEAD\\tREPO and ST\\tPATH\\tSTATUS\\tLAST_COMMIT lines."
  (let ((lines (list "#!/bin/bash")))
    (dolist (repo repos)
      (let ((q (shell-quote-argument (file-name-as-directory (expand-file-name repo)))))
        (push (concat
               "cd " q " 2>/dev/null && {\n"
               "  repo_dir=\"$PWD\"\n"
               "  wt_path=''; branch=''; head=''; bare=0\n"
               "  while IFS= read -r line || [ -n \"$line\" ]; do\n"
               "    case \"$line\" in\n"
               "      'worktree '*) wt_path=\"${line#worktree }\" ;;\n"
               "      'HEAD '*) head=\"${line#HEAD }\" ;;\n"
               "      'branch '*) branch=\"${line#branch }\" ;;\n"
               "      bare) bare=1 ;;\n"
               "      '')\n"
               "        if [ -n \"$wt_path\" ] && [ \"$bare\" -eq 0 ]; then\n"
               "          printf 'WT\\t%s\\t%s\\t%s\\t%s\\n' \"$wt_path\" \"$branch\" \"$head\" \"$repo_dir\"\n"
               "          if [ -d \"$wt_path\" ]; then\n"
               "            s=$(cd \"$wt_path\" && git --no-optional-locks status --porcelain 2>/dev/null)\n"
               "            n=0; [ -n \"$s\" ] && n=$(printf '%s\\n' \"$s\" | wc -l | tr -d ' ')\n"
               "            if [ \"$n\" -eq 0 ]; then ss='clean'\n"
               "            elif [ \"$n\" -eq 1 ]; then ss='1 change'\n"
               "            else ss=\"${n} changes\"; fi\n"
               "            lc=$(cd \"$wt_path\" && git log -1 --format='%cr' 2>/dev/null || echo 'no commits')\n"
               "            printf 'ST\\t%s\\t%s\\t%s\\n' \"$wt_path\" \"$ss\" \"$lc\"\n"
               "          fi\n"
               "        fi\n"
               "        wt_path=''; branch=''; head=''; bare=0\n"
               "        ;;\n"
               "    esac\n"
               "  done < <(git worktree list --porcelain 2>/dev/null; echo)\n"
               "}")
              lines)))
    (mapconcat #'identity (nreverse lines) "\n")))

(defun workbench--parse-full-output (output-buf hidden)
  "Parse output from the full git script.
Returns (worktree-list . status-list).  HIDDEN is a list of paths to exclude."
  (let (worktrees statuses)
    (with-current-buffer output-buf
      (goto-char (point-min))
      (while (not (eobp))
        (let ((line (buffer-substring-no-properties (line-beginning-position) (line-end-position))))
          (cond
           ((string-prefix-p "WT\t" line)
            (let* ((parts (split-string (substring line 3) "\t"))
                   (path (expand-file-name (or (nth 0 parts) "")))
                   (branch-ref (or (nth 1 parts) ""))
                   (branch (if (string-prefix-p "refs/heads/" branch-ref)
                               (substring branch-ref 11)
                             (if (string-empty-p branch-ref) "(detached)" branch-ref)))
                   (head (or (nth 2 parts) ""))
                   (repo (expand-file-name (or (nth 3 parts) ""))))
              (unless (member path hidden)
                (push (list :path path :branch branch :head head :repo repo :bare nil)
                      worktrees))))
           ((string-prefix-p "ST\t" line)
            (let* ((parts (split-string (substring line 3) "\t"))
                   (path (expand-file-name (or (nth 0 parts) "")))
                   (status (or (nth 1 parts) "?"))
                   (last-commit (or (nth 2 parts) "?")))
              (push (list path status last-commit) statuses)))))
        (forward-line 1)))
    (cons (nreverse worktrees) (nreverse statuses))))

(defun workbench--fetch-data (&optional fetch-sessions)
  "Fetch worktree and project data into caches.
When FETCH-SESSIONS is non-nil, also parse Claude sessions for every worktree."
  (setq workbench--wt-cache (workbench--list-all-worktrees))
  (setq workbench--projects-cache (workbench--load-projects))
  ;; Compute git status and last-commit for each worktree
  (let ((ht (make-hash-table :test 'equal)))
    (dolist (wt workbench--wt-cache)
      (let* ((path (plist-get wt :path))
             (sessions (if fetch-sessions (workbench--claude-list-sessions path) nil)))
        (puthash path (list :status (workbench--git-status path)
                            :last-commit (workbench--last-commit-time path)
                            :sessions sessions
                            :sessions-fetched fetch-sessions)
                 ht)))
    (setq workbench--extras-cache ht)))

(defun workbench--fetch-prs-async ()
  "Fetch PR data asynchronously from all repos, then re-render."
  (let* ((repos (workbench--load-repos))
         (buf (current-buffer))
         (remaining (length repos))
         (all-results nil))
    (if (null repos)
        (setq workbench--pr-cache nil)
      (dolist (repo repos)
        (let ((output-buf (generate-new-buffer " *workbench-gh*"))
              (repo-dir (file-name-as-directory (expand-file-name repo))))
          (make-process
           :name (format "workbench-gh-pr-%s" (file-name-nondirectory (directory-file-name repo)))
           :buffer output-buf
           :command (list "bash" "-c"
                          (format "cd %s && NO_COLOR=1 gh pr list --json number,url,state,title,headRefName --limit 100"
                                  (shell-quote-argument repo-dir)))
           :sentinel
           (lambda (proc _event)
             (when (eq (process-status proc) 'exit)
               (unwind-protect
                   (when (= (process-exit-status proc) 0)
                     (condition-case nil
                         (let ((data (with-current-buffer output-buf
                                       (json-read-from-string (buffer-string)))))
                           (cl-loop for item across data
                                    do (push (cons (cdr (assq 'headRefName item))
                                                   (list :number (cdr (assq 'number item))
                                                         :url (cdr (assq 'url item))
                                                         :state (cdr (assq 'state item))
                                                         :title (cdr (assq 'title item))))
                                             all-results)))
                       (error nil)))
                 (kill-buffer output-buf)
                 (setq remaining (1- remaining))
                 (when (and (= remaining 0) (buffer-live-p buf))
                   (with-current-buffer buf
                     (setq workbench--pr-cache all-results)
                     (workbench--rerender))))))))))))

(defun workbench--get-extras (path)
  "Get cached extras for worktree at PATH, or defaults."
  (or (and workbench--extras-cache (gethash path workbench--extras-cache))
      (list :status "?" :last-commit "?" :sessions nil :sessions-fetched nil)))

(defun workbench--order-sessions (sessions project-name wt-path)
  "Reorder SESSIONS according to stored session_order for WT-PATH in PROJECT-NAME.
Unordered sessions (not in session_order) appear first in their original
mtime order, followed by ordered sessions in stored order."
  (if (or (null sessions) (null project-name))
      sessions
    (let ((stored-order (workbench--session-order-for-wt project-name wt-path)))
      (if (null stored-order)
          sessions
        (let* ((unordered (cl-remove-if
                           (lambda (s) (member (plist-get s :id) stored-order))
                           sessions))
               (ordered (cl-loop for id in stored-order
                                 for s = (cl-find id sessions
                                                   :key (lambda (s) (plist-get s :id))
                                                   :test #'equal)
                                 when s collect s)))
          (append unordered ordered))))))

(defun workbench--get-sessions (wt-path)
  "Get sessions for WT-PATH, fetching lazily on first access."
  (let ((extras (workbench--get-extras wt-path)))
    (if (plist-get extras :sessions-fetched)
        (plist-get extras :sessions)
      ;; Fetch now and cache
      (let ((sessions (workbench--claude-list-sessions wt-path)))
        (when workbench--extras-cache
          (puthash wt-path (plist-put (plist-put extras :sessions sessions)
                                       :sessions-fetched t)
                   workbench--extras-cache))
        sessions))))

(defun workbench--rerender ()
  "Re-render the buffer from cached data (fast, no I/O)."
  (let ((inhibit-read-only t)
        (line (line-number-at-pos))
        (all-wts (or workbench--wt-cache nil))
        (projects (or workbench--projects-cache nil))
        (assigned-paths (make-hash-table :test 'equal)))
    (erase-buffer)
    ;; Header line
    (insert (workbench--render-column-header) "\n")
    ;; Projects
    (dolist (project projects)
      (let* ((name (workbench--project-name project))
             (pwts (workbench--project-worktrees project))
             (wt-count (length pwts))
             (fold-key (format "project:%s" name))
             (expanded (workbench--fold-get fold-key t)))
        ;; Project header
        (let ((beg (point)))
          (insert (propertize (format "%s %s (%d worktree%s)"
                                      (if expanded "▼" "▶")
                                      name wt-count
                                      (if (= wt-count 1) "" "s"))
                              'face 'workbench-project-face))
          (put-text-property beg (point)
                             'workbench-node
                             (list :type 'project :name name :expanded expanded))
          (insert "\n"))
        ;; Worktrees under this project
        (when expanded
          (dolist (pw pwts)
            (let* ((wt-path (expand-file-name (cdr (assq 'worktree_path pw))))
                   (matching (cl-find wt-path all-wts
                                      :key (lambda (w) (plist-get w :path))
                                      :test #'equal)))
              (puthash wt-path t assigned-paths)
              (when matching
                (workbench--insert-worktree-node matching name)))))))
    ;; Unassigned worktrees
    (let* ((unassigned (cl-remove-if (lambda (wt) (gethash (plist-get wt :path) assigned-paths))
                                      all-wts))
           (wt-count (length unassigned)))
      (when unassigned
        (let* ((fold-key "project:None")
               (expanded (workbench--fold-get fold-key t))
               (beg (point)))
          (insert (propertize (format "%s No Project (%d worktree%s)"
                                      (if expanded "▼" "▶")
                                      wt-count
                                      (if (= wt-count 1) "" "s"))
                              'face '(:weight bold :slant italic)))
          (put-text-property beg (point)
                             'workbench-node
                             (list :type 'project :name nil :expanded expanded))
          (insert "\n")
          (when expanded
            (dolist (wt unassigned)
              (workbench--insert-worktree-node wt nil))))))
    ;; Header-line
    (setq header-line-format
          (format " workbench — %d project%s · %d worktree%s"
                  (length projects) (if (= (length projects) 1) "" "s")
                  (length all-wts) (if (= (length all-wts) 1) "" "s")))
    ;; Restore cursor
    (goto-char (point-min))
    (forward-line (1- line))
    (beginning-of-line)
    (when (eobp) (forward-line -1))
    (workbench--ensure-on-node)))

(defun workbench--insert-worktree-node (wt project-name)
  "Insert a worktree node for WT under PROJECT-NAME."
  (let* ((path (plist-get wt :path))
         (extras (workbench--get-extras path))
         (fold-key (format "worktree:%s" path))
         (expanded (workbench--fold-get fold-key nil))
         ;; Only fetch sessions when expanded (lazy)
         (raw-sessions (if expanded (workbench--get-sessions path)
                          (plist-get extras :sessions)))
         (sessions (workbench--order-sessions raw-sessions project-name path))
         (prefix (if (and sessions expanded) "  ▼ " (if sessions "  ▶ " "    ")))
         ;; Merge sessions into extras for rendering
         (render-extras (plist-put (copy-sequence extras) :sessions sessions))
         (beg (point)))
    (insert prefix)
    (insert (workbench--render-worktree-line wt render-extras))
    (put-text-property beg (point)
                       'workbench-node
                       (list :type 'worktree
                             :wt wt
                             :sessions sessions
                             :project-name project-name
                             :expanded expanded))
    (insert "\n")
    (when (and sessions expanded)
      (dolist (s sessions)
        (let ((sbeg (point)))
          (insert (workbench--render-session-line s))
          (put-text-property sbeg (point)
                             'workbench-node
                             (list :type 'session
                                   :session s
                                   :wt wt
                                   :project-name project-name))
          (insert "\n"))))))

(defun workbench--node-at-point ()
  "Return the workbench-node plist at point, or nil."
  (get-text-property (line-beginning-position) 'workbench-node))

(defun workbench--ensure-on-node ()
  "Move to the nearest node line if currently on a non-node line (like the header)."
  (unless (workbench--node-at-point)
    (forward-line 1)
    (unless (workbench--node-at-point)
      (goto-char (point-min))
      (forward-line 1))))

(defun workbench--wt-at-point ()
  "Return the worktree plist at point.
Works for worktree lines and session lines (returns parent worktree)."
  (let ((node (workbench--node-at-point)))
    (when node
      (pcase (plist-get node :type)
        ('worktree (plist-get node :wt))
        ('session (plist-get node :wt))))))

(defun workbench--project-at-point ()
  "Return the project name at point if on a project line."
  (let ((node (workbench--node-at-point)))
    (when (and node (eq (plist-get node :type) 'project))
      (plist-get node :name))))

(defun workbench--session-at-point ()
  "Return the session plist at point."
  (let ((node (workbench--node-at-point)))
    (when (and node (eq (plist-get node :type) 'session))
      (plist-get node :session))))

;; ══════════════════════════════════════════════════════════════════
;; Interactive commands
;; ══════════════════════════════════════════════════════════════════

(defun workbench-toggle-fold ()
  "Toggle expand/collapse of the node at point."
  (interactive)
  (let ((node (workbench--node-at-point)))
    (unless node (user-error "No node at point"))
    (pcase (plist-get node :type)
      ('project
       (let* ((name (plist-get node :name))
              (key (format "project:%s" (or name "None")))
              (currently-expanded (plist-get node :expanded)))
         (workbench--fold-set key (not currently-expanded))
         (workbench--rerender)))
      ('worktree
       (let* ((wt (plist-get node :wt))
              (key (format "worktree:%s" (plist-get wt :path)))
              (currently-expanded (plist-get node :expanded)))
         (workbench--fold-set key (not currently-expanded))
         (workbench--rerender)))
      ('session
       ;; Collapse parent worktree and move cursor to it
       (let* ((wt (plist-get node :wt))
              (key (format "worktree:%s" (plist-get wt :path))))
         (workbench--fold-set key nil)
         (workbench--rerender)
         ;; Find the parent worktree line and move cursor there
         (goto-char (point-min))
         (catch 'found
           (while (not (eobp))
             (let ((n (workbench--node-at-point)))
               (when (and n
                          (eq (plist-get n :type) 'worktree)
                          (equal (plist-get (plist-get n :wt) :path)
                                 (plist-get wt :path)))
                 (throw 'found nil)))
             (forward-line 1))))))))

;; Default tool launcher implementations

(defun workbench-open-claude-default (dir)
  "Default: open Claude in a terminal at DIR, resuming most recent session."
  (let* ((sessions (workbench--claude-list-sessions dir))
         (cmd (if sessions
                  (workbench--claude-resume-cmd (plist-get (car sessions) :id))
                (workbench--claude-open-cmd))))
    (workbench--run-in-terminal cmd dir)))

(defun workbench-new-session-default (dir)
  "Default: open a new Claude session in a terminal at DIR."
  (workbench--run-in-terminal (workbench--claude-open-cmd) dir))

(defun workbench-resume-session-default (dir session)
  "Default: resume Claude SESSION in a terminal at DIR."
  (workbench--run-in-terminal (workbench--claude-resume-cmd (plist-get session :id)) dir))

(defun workbench-fork-session-default (dir session)
  "Default: fork Claude SESSION in a new terminal at DIR."
  (workbench--run-in-terminal (workbench--claude-resume-cmd (plist-get session :id)) dir))

(defun workbench-open-ide-default (dir)
  "Default: open IDE at DIR using `workbench-ide' setting."
  (workbench--open-ide dir))

(defun workbench-open-git-default (dir)
  "Default: open VCS client at DIR using `workbench-vcs-client' setting."
  (workbench--open-vcs dir))

(defun workbench-open-terminal-default (dir)
  "Default: open terminal at DIR using `workbench-terminal' setting."
  (workbench--open-terminal dir))

;; Interactive commands — dispatch through customizable functions

(defun workbench-open-claude ()
  "Open Claude for the worktree at point."
  (interactive)
  (let ((wt (workbench--wt-at-point)))
    (unless wt (user-error "No worktree at point"))
    (funcall workbench-open-claude-function (plist-get wt :path))
    (message "Opened Claude for %s" (plist-get wt :branch))))

(defun workbench-new-session ()
  "Open a new Claude session for the worktree at point."
  (interactive)
  (let ((wt (workbench--wt-at-point)))
    (unless wt (user-error "No worktree at point"))
    (funcall workbench-new-session-function (plist-get wt :path))
    (message "New Claude session for %s" (plist-get wt :branch))))

(defun workbench-resume-session ()
  "Resume the Claude session at point."
  (interactive)
  (let ((session (workbench--session-at-point)))
    (unless session (user-error "No session at point"))
    (let ((wt (workbench--wt-at-point)))
      (funcall workbench-resume-session-function (plist-get wt :path) session)
      (message "Resumed session for %s" (plist-get wt :branch)))))

(defun workbench-fork-session ()
  "Fork the Claude session at point."
  (interactive)
  (let ((session (workbench--session-at-point)))
    (unless session (user-error "No session at point"))
    (let ((wt (workbench--wt-at-point)))
      (funcall workbench-fork-session-function (plist-get wt :path) session)
      (message "Forked session for %s" (plist-get wt :branch)))))

(defun workbench-open-ide ()
  "Open IDE for the worktree at point."
  (interactive)
  (let ((wt (workbench--wt-at-point)))
    (unless wt (user-error "No worktree at point"))
    (funcall workbench-open-ide-function (plist-get wt :path))
    (message "Opened IDE for %s" (plist-get wt :branch))))

(defun workbench-open-git ()
  "Open VCS client for the worktree at point."
  (interactive)
  (let ((wt (workbench--wt-at-point)))
    (unless wt (user-error "No worktree at point"))
    (funcall workbench-open-git-function (plist-get wt :path))
    (message "Opened git client for %s" (plist-get wt :branch))))

(defun workbench-open-terminal ()
  "Open a terminal for the worktree at point."
  (interactive)
  (let ((wt (workbench--wt-at-point)))
    (unless wt (user-error "No worktree at point"))
    (funcall workbench-open-terminal-function (plist-get wt :path))
    (message "Opened terminal for %s" (plist-get wt :branch))))

(defun workbench-open-pr ()
  "Open or create PR for the worktree at point."
  (interactive)
  (let ((wt (workbench--wt-at-point)))
    (unless wt (user-error "No worktree at point"))
    (let* ((branch (plist-get wt :branch))
           (pr (cdr (assoc branch workbench--pr-cache))))
      (if pr
          (progn
            (workbench--open-pr-in-browser branch (plist-get wt :path))
            (message "Opened PR #%d in browser" (plist-get pr :number)))
        (let ((base (read-string "Create PR — base branch: " "main")))
          (let ((new-pr (workbench--create-pr branch base (plist-get wt :path))))
            (when new-pr
              (message "Created PR #%d" (plist-get new-pr :number))
              (workbench-refresh))))))))

(defun workbench-close-worktree ()
  "Close/remove the worktree at point."
  (interactive)
  (let* ((node (workbench--node-at-point))
         (wt (workbench--wt-at-point)))
    (unless wt (user-error "No worktree at point"))
    (let ((branch (plist-get wt :branch))
          (project-name (plist-get node :project-name)))
      (when (workbench--has-unpushed-changes (plist-get wt :path) branch)
        (unless (y-or-n-p (format "Branch '%s' has unpushed changes. Close anyway? " branch))
          (user-error "Cancelled")))
      (if (workbench--is-main-worktree wt)
          (progn
            (workbench--hide-worktree (plist-get wt :path))
            (when project-name
              (workbench--remove-worktree-from-project project-name (plist-get wt :path)))
            (message "Hidden worktree %s" branch))
        (when project-name
          (workbench--remove-worktree-from-project project-name (plist-get wt :path)))
        (workbench--remove-worktree (plist-get wt :path))
        (message "Removed worktree %s" branch))
      (workbench-refresh))))

(defun workbench-new-worktree ()
  "Create a new worktree."
  (interactive)
  (let* ((repos (workbench--load-repos))
         (_ (unless repos (user-error "No repos registered.  Use R to add one")))
         (repo-names (workbench--disambiguate-paths repos))
         (repo-choice (completing-read "Repo: " (mapcar #'car repo-names) nil t))
         (repo-path (cdr (assoc repo-choice repo-names)))
         (branch (read-string "Branch name: "))
         (projects (workbench--load-projects))
         (project-names (cons "(no project)" (mapcar #'workbench--project-name projects)))
         (project-choice (completing-read "Project: " project-names nil t))
         (project-name (unless (string= project-choice "(no project)") project-choice)))
    (when (string-empty-p branch) (user-error "Branch name cannot be empty"))
    (let ((wt (workbench--create-worktree repo-path branch)))
      (when project-name
        (workbench--add-worktree-to-project project-name repo-path branch (plist-get wt :path)))
      (message "Created worktree for %s" branch)
      (workbench-refresh))))

(defun workbench-new-project ()
  "Create a new project."
  (interactive)
  (let ((name (read-string "Project name: ")))
    (when (string-empty-p name) (user-error "Project name cannot be empty"))
    (workbench--create-project name)
    (message "Created project '%s'" name)
    (workbench-refresh)))

(defun workbench-add-repo ()
  "Register a git repo."
  (interactive)
  (let ((path (read-directory-name "Repo path: ")))
    (unless (file-exists-p (expand-file-name ".git" path))
      (user-error "Not a git repo: %s" path))
    (workbench--add-repo path)
    (message "Added repo: %s" path)
    (workbench-refresh)))

(defun workbench-archive-project ()
  "Archive the project at point, closing all its worktrees."
  (interactive)
  (let ((name (workbench--project-at-point)))
    (unless name (user-error "No project at point"))
    (let* ((project (cl-find name (workbench--load-projects)
                             :key #'workbench--project-name :test #'equal))
           (pwts (workbench--project-worktrees project))
           (all-wts (or workbench--wt-cache (workbench--list-all-worktrees)))
           (live-wts (cl-loop for pw in pwts
                              for path = (expand-file-name (cdr (assq 'worktree_path pw)))
                              for wt = (cl-find path all-wts
                                                :key (lambda (w) (plist-get w :path))
                                                :test #'equal)
                              when wt collect wt))
           (has-unpushed (cl-some (lambda (wt)
                                    (workbench--has-unpushed-changes
                                     (plist-get wt :path) (plist-get wt :branch)))
                                  live-wts)))
      (when has-unpushed
        (unless (y-or-n-p (format "Project '%s' has worktrees with unpushed changes. Archive anyway? " name))
          (user-error "Cancelled")))
      (dolist (wt live-wts)
        (if (workbench--is-main-worktree wt)
            (workbench--hide-worktree (plist-get wt :path))
          (condition-case err
              (workbench--remove-worktree (plist-get wt :path))
            (error (message "Warning: %s" (error-message-string err))))))
      (workbench--archive-project name)
      (message "Archived project %s" name)
      (workbench-refresh))))

(defun workbench-assign-to-project ()
  "Assign the worktree at point to a project."
  (interactive)
  (let ((wt (workbench--wt-at-point)))
    (unless wt (user-error "No worktree at point"))
    (let* ((projects (workbench--load-projects))
           (names (mapcar #'workbench--project-name projects))
           (choice (completing-read "Assign to project: " names nil t))
           (wt-path (plist-get wt :path))
           (current-project (workbench--find-project-for-worktree wt-path)))
      (when current-project
        (workbench--remove-worktree-from-project current-project wt-path))
      (workbench--add-worktree-to-project choice (plist-get wt :repo) (plist-get wt :branch) wt-path)
      (message "Assigned %s to %s" (plist-get wt :branch) choice)
      (workbench-refresh))))

(defun workbench--move-project (name direction)
  "Move project NAME in DIRECTION (-1 for up, +1 for down).
Persists the new order and moves the cursor to follow."
  (let* ((all (workbench--load-all-projects))
         (active (cl-remove-if (lambda (p) (eq (cdr (assq 'archived p)) t)) all))
         (archived (cl-remove-if-not (lambda (p) (eq (cdr (assq 'archived p)) t)) all))
         (idx (cl-position name active :key #'workbench--project-name :test #'equal))
         (target (when idx (+ idx direction))))
    (when (and target (>= target 0) (< target (length active)))
      (let ((item (nth idx active)))
        (setf (nth idx active) (nth target active))
        (setf (nth target active) item))
      (workbench--save-all-projects (append active archived))
      (setq workbench--projects-cache active)
      (workbench--rerender)
      (workbench--goto-node 'project name))))

(defun workbench--move-worktree (wt-path project-name direction)
  "Move worktree at WT-PATH within PROJECT-NAME by DIRECTION (-1/+1)."
  (unless project-name (user-error "Cannot reorder unassigned worktrees"))
  (let* ((all (workbench--load-all-projects))
         (project (cl-find project-name all :key #'workbench--project-name :test #'equal)))
    (when project
      (let* ((wts (append (cdr (assq 'worktrees project)) nil))
             (idx (cl-position wt-path wts
                               :key (lambda (w) (expand-file-name (cdr (assq 'worktree_path w))))
                               :test #'equal))
             (target (when idx (+ idx direction))))
        (when (and target (>= target 0) (< target (length wts)))
          (let ((item (nth idx wts)))
            (setf (nth idx wts) (nth target wts))
            (setf (nth target wts) item))
          (setcdr (assq 'worktrees project) (vconcat wts))
          (workbench--save-all-projects all)
          ;; Update cache
          (setq workbench--projects-cache
                (cl-remove-if (lambda (p) (eq (cdr (assq 'archived p)) t)) all))
          (workbench--rerender)
          (workbench--goto-node 'worktree wt-path))))))

(defun workbench--session-order-for-wt (project-name wt-path)
  "Get session_order list for WT-PATH in PROJECT-NAME, or nil."
  (when project-name
    (let* ((all (workbench--load-all-projects))
           (project (cl-find project-name all :key #'workbench--project-name :test #'equal)))
      (when project
        (let* ((wts (append (cdr (assq 'worktrees project)) nil))
               (wt-entry (cl-find (expand-file-name wt-path) wts
                                   :key (lambda (w) (expand-file-name (cdr (assq 'worktree_path w))))
                                   :test #'equal)))
          (when wt-entry
            (let ((order (cdr (assq 'session_order wt-entry))))
              (when order (append order nil)))))))))

(defun workbench--save-session-order (project-name wt-path order)
  "Save session ORDER (list of id strings) for WT-PATH in PROJECT-NAME."
  (when project-name
    (let* ((all (workbench--load-all-projects))
           (project (cl-find project-name all :key #'workbench--project-name :test #'equal)))
      (when project
        (let* ((wts (append (cdr (assq 'worktrees project)) nil))
               (wt-entry (cl-find (expand-file-name wt-path) wts
                                   :key (lambda (w) (expand-file-name (cdr (assq 'worktree_path w))))
                                   :test #'equal)))
          (when wt-entry
            (if (assq 'session_order wt-entry)
                (setcdr (assq 'session_order wt-entry) (vconcat order))
              (nconc wt-entry (list (cons 'session_order (vconcat order)))))
            (setcdr (assq 'worktrees project) (vconcat wts))
            (workbench--save-all-projects all)
            (setq workbench--projects-cache
                  (cl-remove-if (lambda (p) (eq (cdr (assq 'archived p)) t)) all))))))))

(defun workbench--move-session (session-id wt project-name direction)
  "Move session SESSION-ID within WT by DIRECTION (-1/+1)."
  (unless project-name (user-error "Cannot reorder sessions for unassigned worktrees"))
  (let* ((wt-path (plist-get wt :path))
         (current-sessions (workbench--get-sessions wt-path))
         (current-ids (mapcar (lambda (s) (plist-get s :id)) current-sessions))
         (stored-order (workbench--session-order-for-wt project-name wt-path))
         ;; Materialize: unordered (not in stored-order) first by mtime, then ordered
         (display-order
          (if stored-order
              (let* ((unordered (cl-remove-if (lambda (id) (member id stored-order)) current-ids))
                     (ordered (cl-remove-if-not (lambda (id) (member id current-ids)) stored-order)))
                (append unordered ordered))
            current-ids))
         (idx (cl-position session-id display-order :test #'equal))
         (target (when idx (+ idx direction))))
    (when (and target (>= target 0) (< target (length display-order)))
      (let ((item (nth idx display-order)))
        (setf (nth idx display-order) (nth target display-order))
        (setf (nth target display-order) item))
      ;; Persist the full order
      (workbench--save-session-order project-name wt-path display-order)
      ;; Reorder cached sessions in memory (no disk re-read)
      (when workbench--extras-cache
        (let ((extras (gethash wt-path workbench--extras-cache)))
          (when extras
            (let* ((cached-sessions (plist-get extras :sessions))
                   (reordered (cl-loop for id in display-order
                                       for s = (cl-find id cached-sessions
                                                         :key (lambda (s) (plist-get s :id))
                                                         :test #'equal)
                                       when s collect s)))
              (puthash wt-path (plist-put (plist-put extras :sessions reordered)
                                           :sessions-fetched t)
                       workbench--extras-cache)))))
      (workbench--rerender)
      (workbench--goto-node 'session session-id))))

(defun workbench--goto-node (type identifier)
  "Move cursor to the node of TYPE matching IDENTIFIER after a rerender.
For project: IDENTIFIER is name.  For worktree: IDENTIFIER is path.
For session: IDENTIFIER is session id."
  (goto-char (point-min))
  (let ((target-line nil))
    (while (not (eobp))
      (let ((node (workbench--node-at-point)))
        (when node
          (pcase type
            ('project
             (when (and (eq (plist-get node :type) 'project)
                        (equal (plist-get node :name) identifier))
               (setq target-line (line-number-at-pos))))
            ('worktree
             (when (and (eq (plist-get node :type) 'worktree)
                        (equal (plist-get (plist-get node :wt) :path) identifier))
               (setq target-line (line-number-at-pos))))
            ('session
             (when (and (eq (plist-get node :type) 'session)
                        (equal (plist-get (plist-get node :session) :id) identifier))
               (setq target-line (line-number-at-pos)))))))
      (forward-line 1))
    (when target-line
      (goto-char (point-min))
      (forward-line (1- target-line)))))

(defun workbench-move-up ()
  "Move the item at point up one position."
  (interactive)
  (let ((node (workbench--node-at-point)))
    (unless node (user-error "No item at point"))
    (pcase (plist-get node :type)
      ('project
       (let ((name (plist-get node :name)))
         (unless name (user-error "Cannot move this item"))
         (workbench--move-project name -1)))
      ('worktree
       (workbench--move-worktree (plist-get (plist-get node :wt) :path)
                                  (plist-get node :project-name) -1))
      ('session
       (workbench--move-session (plist-get (plist-get node :session) :id)
                                 (plist-get node :wt)
                                 (plist-get node :project-name) -1)))))

(defun workbench-move-down ()
  "Move the item at point down one position."
  (interactive)
  (let ((node (workbench--node-at-point)))
    (unless node (user-error "No item at point"))
    (pcase (plist-get node :type)
      ('project
       (let ((name (plist-get node :name)))
         (unless name (user-error "Cannot move this item"))
         (workbench--move-project name 1)))
      ('worktree
       (workbench--move-worktree (plist-get (plist-get node :wt) :path)
                                  (plist-get node :project-name) 1))
      ('session
       (workbench--move-session (plist-get (plist-get node :session) :id)
                                 (plist-get node :wt)
                                 (plist-get node :project-name) 1)))))

(defun workbench-view-archived ()
  "Show archived projects in a separate buffer."
  (interactive)
  (let ((archived (workbench--load-archived-projects)))
    (unless archived (user-error "No archived projects"))
    (let ((buf (get-buffer-create "*workbench-archived*")))
      (with-current-buffer buf
        (workbench-archived-mode)
        (workbench-archived--refresh))
      (pop-to-buffer buf))))

;; ══════════════════════════════════════════════════════════════════
;; Archived projects mode
;; ══════════════════════════════════════════════════════════════════

(defvar workbench-archived-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "u") #'workbench-archived-unarchive)
    (define-key map (kbd "X") #'workbench-archived-delete)
    (define-key map (kbd "q") #'quit-window)
    (define-key map (kbd "n") #'next-line)
    (define-key map (kbd "p") #'previous-line)
    map))

(define-derived-mode workbench-archived-mode special-mode "Workbench-Archived"
  "Mode for viewing archived workbench projects."
  (setq header-line-format " Archived Projects")
  (hl-line-mode 1))

(defun workbench-archived--refresh ()
  "Refresh the archived projects buffer."
  (let ((inhibit-read-only t)
        (archived (workbench--load-archived-projects)))
    (erase-buffer)
    (if (null archived)
        (insert "No archived projects.\n")
      (dolist (p archived)
        (let ((beg (point)))
          (insert (format "  %s  (%d worktrees)\n"
                          (workbench--project-name p)
                          (length (workbench--project-worktrees p))))
          (put-text-property beg (1- (point)) 'workbench-archived-name
                             (workbench--project-name p)))))
    (goto-char (point-min))))

(defun workbench-archived--name-at-point ()
  "Return archived project name at point."
  (get-text-property (point) 'workbench-archived-name))

(defun workbench-archived-unarchive ()
  "Unarchive the project at point."
  (interactive)
  (let ((name (workbench-archived--name-at-point)))
    (unless name (user-error "No project at point"))
    (workbench--unarchive-project name)
    (message "Restored project %s" name)
    (workbench-archived--refresh)
    (workbench-refresh)))

(defun workbench-archived-delete ()
  "Delete the archived project at point."
  (interactive)
  (let ((name (workbench-archived--name-at-point)))
    (unless name (user-error "No project at point"))
    (when (y-or-n-p (format "Permanently delete project '%s'? " name))
      (workbench--delete-project name)
      (message "Deleted project %s" name)
      (workbench-archived--refresh)
      (workbench-refresh))))

;; ══════════════════════════════════════════════════════════════════
;; Transient (? key help popup)
;; ══════════════════════════════════════════════════════════════════

(transient-define-prefix workbench-dispatch ()
  "Workbench command dispatcher."
  ["Launch"
   ("c" "Claude" workbench-open-claude)
   ("o" "New session" workbench-new-session)
   ("i" "IDE" workbench-open-ide)
   ("g" "Git client" workbench-open-git)
   ("t" "Terminal" workbench-open-terminal)
   ("p" "PR" workbench-open-pr)]
  ["Worktree"
   ("n" "New worktree" workbench-new-worktree)
   ("x" "Close worktree" workbench-close-worktree)
   ("a" "Assign to project" workbench-assign-to-project)]
  ["Session"
   ("s" "Resume" workbench-resume-session)
   ("f" "Fork" workbench-fork-session)]
  ["Project"
   ("P" "New project" workbench-new-project)
   ("A" "Archive project" workbench-archive-project)
   ("d" "View archived" workbench-view-archived)]
  ["Other"
   ("[" "Move up" workbench-move-up)
   ("]" "Move down" workbench-move-down)
   ("R" "Add repo" workbench-add-repo)
   ("r" "Refresh" workbench-refresh)
   ("q" "Quit" quit-window)])

;; ══════════════════════════════════════════════════════════════════
;; Major mode
;; ══════════════════════════════════════════════════════════════════

(defvar workbench-mode-map nil)
(setq workbench-mode-map
  (let ((map (make-sparse-keymap)))
    ;; Navigation
    (define-key map (kbd "RET") #'workbench-toggle-fold)
    (define-key map (kbd "TAB") #'workbench-toggle-fold)
    ;; Launch tools
    (define-key map (kbd "c") #'workbench-open-claude)
    (define-key map (kbd "o") #'workbench-new-session)
    (define-key map (kbd "s") #'workbench-resume-session)
    (define-key map (kbd "f") #'workbench-fork-session)
    (define-key map (kbd "i") #'workbench-open-ide)
    (define-key map (kbd "g") #'workbench-open-git)
    (define-key map (kbd "t") #'workbench-open-terminal)
    (define-key map (kbd "p") #'workbench-open-pr)
    ;; Worktree management
    (define-key map (kbd "x") #'workbench-close-worktree)
    (define-key map (kbd "n") #'workbench-new-worktree)
    (define-key map (kbd "P") #'workbench-new-project)
    (define-key map (kbd "R") #'workbench-add-repo)
    (define-key map (kbd "A") #'workbench-archive-project)
    (define-key map (kbd "a") #'workbench-assign-to-project)
    (define-key map (kbd "d") #'workbench-view-archived)
    (define-key map (kbd "[") #'workbench-move-up)
    (define-key map (kbd "]") #'workbench-move-down)
    ;; Other
    (define-key map (kbd "r") #'workbench-refresh)
    (define-key map (kbd "?") #'workbench-dispatch)
    (define-key map (kbd "q") #'quit-window)
    map))

(define-derived-mode workbench-mode special-mode "Workbench"
  "Major mode for the workbench worktree manager.

Press \\[workbench-dispatch] for a full list of keybindings."
  (setq-local revert-buffer-function (lambda (_ignore-auto _noconfirm) (workbench-refresh)))
  (setq truncate-lines t)
  (hl-line-mode 1)
  ;; Start auto-refresh timer
  (when workbench--refresh-timer
    (cancel-timer workbench--refresh-timer))
  (setq workbench--refresh-timer
        (run-with-timer workbench-refresh-interval workbench-refresh-interval
                        #'workbench--quick-refresh)))

;;;###autoload
(defun workbench ()
  "Open the workbench worktree manager."
  (interactive)
  (let ((buf (get-buffer-create "*workbench*")))
    (with-current-buffer buf
      (unless (eq major-mode 'workbench-mode)
        (workbench-mode))
      (workbench--async-refresh nil))
    (pop-to-buffer buf)))

(defun workbench--kill-buffer-hook ()
  "Clean up when the workbench buffer is killed."
  (when (string= (buffer-name) "*workbench*")
    (when workbench--refresh-timer
      (cancel-timer workbench--refresh-timer)
      (setq workbench--refresh-timer nil))))

(add-hook 'kill-buffer-hook #'workbench--kill-buffer-hook)

;; ══════════════════════════════════════════════════════════════════
;; Custom opener: kyle-git-opener-workflow
;; ══════════════════════════════════════════════════════════════════
;;
;; Multi-monitor magit workflow:
;;
;; Targets a frame OTHER than the one containing the *workbench* buffer.
;;
;; - 1 window, showing magit for the SAME worktree → focus that window
;; - 1 window, showing magit for a DIFFERENT repo → split, open new magit
;; - 1 window, NOT magit → open magit there
;; - 2+ windows → pick the least recently used, open magit there

(defun kyle-git-opener-workflow (dir)
  "Open magit-status for DIR in another frame using multi-monitor workflow."
  (unless (fboundp 'magit-status) (user-error "magit not available"))
  (let* ((dir (expand-file-name dir))
         (target-frame (kyle--find-other-frame)))
    (unless target-frame (user-error "No other frame found"))
    (with-selected-frame target-frame
      (raise-frame target-frame)
      (let ((windows (window-list target-frame 'no-mini)))
        (cond
         ;; Single window
         ((= (length windows) 1)
          (let ((win (car windows)))
            (cond
             ;; Already showing magit for this exact dir — just focus
             ((kyle--window-shows-magit-for-dir-p win dir)
              (select-window win)
              (select-frame-set-input-focus target-frame))
             ;; Showing magit for a different repo — split and open
             ((kyle--window-shows-magit-p win)
              (let ((new-win (split-window win nil 'right)))
                (select-window new-win)
                (magit-status dir)
                (select-frame-set-input-focus target-frame)))
             ;; Not magit at all — open magit here
             (t
              (select-window win)
              (magit-status dir)
              (select-frame-set-input-focus target-frame)))))
         ;; 2+ windows — pick LRU
         (t
          (let ((lru-win (kyle--least-recently-used-window windows)))
            (select-window lru-win)
            (magit-status dir)
            (select-frame-set-input-focus target-frame))))))))

(defun kyle--find-other-frame ()
  "Find a visible frame that is NOT the one showing *workbench*.
Returns nil if no other frame exists."
  (let ((wb-frame (selected-frame)))
    (cl-loop for frame in (frame-list)
             when (and (frame-visible-p frame)
                       (not (eq frame wb-frame))
                       ;; Skip tooltip frames, child frames, etc.
                       (not (frame-parameter frame 'parent-frame))
                       (not (eq (frame-parameter frame 'minibuffer) 'only)))
             return frame)))

(defun kyle--window-shows-magit-p (win)
  "Return non-nil if WIN is displaying a magit-status buffer."
  (with-current-buffer (window-buffer win)
    (derived-mode-p 'magit-status-mode)))

(defun kyle--window-shows-magit-for-dir-p (win dir)
  "Return non-nil if WIN shows magit-status for DIR."
  (with-current-buffer (window-buffer win)
    (and (derived-mode-p 'magit-status-mode)
         (string= (expand-file-name default-directory)
                  (file-name-as-directory (expand-file-name dir))))))

(defun kyle--least-recently-used-window (windows)
  "Return the window from WINDOWS with the lowest `window-use-time'."
  (cl-reduce (lambda (a b)
               (if (< (window-use-time a) (window-use-time b)) a b))
             windows))

;; To use: (setq workbench-open-git-function #'kyle-git-opener-workflow)

;; ══════════════════════════════════════════════════════════════════
;; Custom opener: kyle-terminal-workflow / kyle-claude-workflow
;; ══════════════════════════════════════════════════════════════════
;;
;; Opens commands as new tabs in the existing Terminal.app window
;; rather than spawning new windows.

(defun kyle--run-in-terminal-tab (cmd cwd)
  "Run CMD (string) in CWD as a new tab in the existing Terminal.app window.
Uses `open -g` to avoid bringing other Terminal windows to the front.
Requires macOS Prefer Tabs setting: System Settings > Desktop & Dock >
Windows & Apps > Prefer tabs when opening documents > Always."
  (let* ((cwd (expand-file-name cwd))
         (script-file (make-temp-file "workbench-" nil ".command"
                                      (format "#!/bin/bash\ncd %s\n%s\n"
                                              (shell-quote-argument cwd) cmd))))
    (set-file-modes script-file #o755)
    (start-process "kyle-term-tab" nil "open" "-g" "-a" "Terminal" script-file)))

(defun kyle--cmd-to-shell-string (cmd)
  "Convert CMD (list of strings) to a shell command string."
  (mapconcat #'shell-quote-argument cmd " "))

(defun kyle--run-in-terminal-tab-steal-focus (cmd cwd)
  "Like `kyle--run-in-terminal-tab' but brings Terminal to the foreground."
  (let* ((cwd (expand-file-name cwd))
         (script-file (make-temp-file "workbench-" nil ".command"
                                      (format "#!/bin/bash\ncd %s\n%s\n"
                                              (shell-quote-argument cwd) cmd))))
    (set-file-modes script-file #o755)
    (start-process "kyle-term-tab" nil "open" "-a" "Terminal" script-file)))

(defun kyle-terminal-workflow (dir)
  "Open a new Terminal.app tab at DIR."
  (kyle--run-in-terminal-tab "exec $SHELL" dir))

(defun kyle-terminal-workflow-steal-focus (dir)
  "Open a new Terminal.app tab at DIR and bring Terminal to the foreground."
  (kyle--run-in-terminal-tab-steal-focus "exec $SHELL" dir))

(defun kyle-claude-workflow (dir)
  "Open Claude in a Terminal.app tab at DIR, resuming most recent session."
  (let* ((sessions (workbench--claude-list-sessions dir))
         (cmd (kyle--cmd-to-shell-string
               (if sessions
                   (workbench--claude-resume-cmd (plist-get (car sessions) :id))
                 (workbench--claude-open-cmd)))))
    (kyle--run-in-terminal-tab cmd dir)))

(defun kyle-new-session-workflow (dir)
  "Open a new Claude session in a Terminal.app tab at DIR."
  (kyle--run-in-terminal-tab (kyle--cmd-to-shell-string (workbench--claude-open-cmd)) dir))

(defun kyle-resume-session-workflow (dir session)
  "Resume Claude SESSION in a Terminal.app tab at DIR."
  (kyle--run-in-terminal-tab
   (kyle--cmd-to-shell-string (workbench--claude-resume-cmd (plist-get session :id)))
   dir))

(defun kyle-fork-session-workflow (dir session)
  "Fork Claude SESSION in a Terminal.app tab at DIR."
  (kyle--run-in-terminal-tab
   (kyle--cmd-to-shell-string (workbench--claude-resume-cmd (plist-get session :id)))
   dir))

;; To use:
;; (setq workbench-open-terminal-function #'kyle-terminal-workflow)
;; (setq workbench-open-claude-function #'kyle-claude-workflow)
;; (setq workbench-new-session-function #'kyle-new-session-workflow)
;; (setq workbench-resume-session-function #'kyle-resume-session-workflow)
;; (setq workbench-fork-session-function #'kyle-fork-session-workflow)

(defun kyle-git-debug ()
  "Debug the multi-frame git opener."
  (interactive)
  (message "=== KYLE GIT DEBUG ===")
  (message "workbench-open-git-function: %S" workbench-open-git-function)
  (message "Current frame: %S" (selected-frame))
  (message "All frames: %d" (length (frame-list)))
  (dolist (f (frame-list))
    (message "  frame %S visible=%s parent=%s mini-only=%s"
             f
             (frame-visible-p f)
             (frame-parameter f 'parent-frame)
             (eq (frame-parameter f 'minibuffer) 'only)))
  (let ((other (kyle--find-other-frame)))
    (message "Other frame found: %S" other)))

(defun workbench-debug ()
  "Print debug info to *Messages*."
  (interactive)
  (let* ((repos (workbench--load-repos))
         (all-wts (workbench--list-all-worktrees))
         (projects (workbench--load-projects)))
    (message "=== WORKBENCH DEBUG ===")
    (message "Repos: %S" repos)
    (message "Hidden: %S" (workbench--load-hidden-worktrees))
    (dolist (repo repos)
      (message "Repo %s exists: %s" repo (file-directory-p repo))
      (let ((raw (workbench--git-output repo "worktree" "list" "--porcelain")))
        (message "  git output nil? %s" (null raw))
        (when raw (message "  git output (first 200): %s" (substring raw 0 (min 200 (length raw))))))
      (let ((wts (workbench--list-worktrees-for-repo repo)))
        (message "  parsed worktrees: %d" (length wts))
        (dolist (wt wts)
          (message "    wt: path=%s branch=%s bare=%s" (plist-get wt :path) (plist-get wt :branch) (plist-get wt :bare)))))
    (message "Total worktrees after filtering: %d" (length all-wts))
    (dolist (wt all-wts)
      (message "  WT: path=%s branch=%s" (plist-get wt :path) (plist-get wt :branch)))
    (message "Projects: %d" (length projects))
    (dolist (p projects)
      (message "  Project: %s" (workbench--project-name p))
      (dolist (pw (workbench--project-worktrees p))
        (message "    pw path: %s" (cdr (assq 'worktree_path pw)))))))

(defun workbench-dev-reload ()
  "Reload workbench.el from the worktree and reopen the buffer."
  (interactive)
  (let ((wb-buf (get-buffer "*workbench*")))
    (when wb-buf
      (kill-buffer wb-buf)))
  (load-file (expand-file-name "~/src/workbench/.worktrees/move-projects-and-wt-around/elisp/workbench.el"))
  (setq workbench-open-git-function #'kyle-git-opener-workflow)
  (setq workbench-open-terminal-function #'kyle-terminal-workflow)
  (setq workbench-open-claude-function #'kyle-claude-workflow)
  (setq workbench-new-session-function #'kyle-new-session-workflow)
  (setq workbench-resume-session-function #'kyle-resume-session-workflow)
  (setq workbench-fork-session-function #'kyle-fork-session-workflow)
  (setq workbench-branch-strip-prefixes '("kylewaldner/" "kyle/" "kylewaldner02/"))
  (workbench))

(provide 'workbench)
;;; workbench.el ends here
