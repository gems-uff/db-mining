CREATE TABLE IF NOT EXISTS project (
   project_id INTEGER PRIMARY KEY AUTOINCREMENT,
   owner TEXT,
   name TEXT,
   createdAt TEXT,
   pushedAt TEXT,
   isMirror BOOLEAN,
   diskUsage INTEGER,
   languages INTEGER,
   contributors INTEGER,
   watchers	INTEGER,
   stargazers INTEGER,
   forks INTEGER,
   issues INTEGER,
   commits INTEGER,
   pullRequests INTEGER,
   branches INTEGER,
   tags INTEGER,
   releases	INTEGER,
   description TEXT,
   primaryLanguage TEXT,
   domain TEXT
);

CREATE TABLE IF NOT EXISTS project_version (
   project_version_id INTEGER PRIMARY KEY AUTOINCREMENT,
   sha1 TEXT,
   last BOOLEAN,
   project_id INTEGER,
   FOREIGN KEY (project_id) REFERENCES project (project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS category (
   category_id INTEGER PRIMARY KEY AUTOINCREMENT,
   name TEXT
);

CREATE TABLE IF NOT EXISTS label (
   label_id INTEGER PRIMARY KEY AUTOINCREMENT,
   name TEXT,
   type TEXT
);

CREATE TABLE IF NOT EXISTS label_category (
   label_id INTEGER NOT NULL,
   category_id INTEGER NOT NULL,
   is_main BOOLEAN,
   PRIMARY KEY (label_id, category_id),
   FOREIGN KEY (label_id) REFERENCES label (label_id) ON DELETE CASCADE,
   FOREIGN KEY (category_id) REFERENCES category (category_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS project_version_label (
   project_version_id INTEGER NOT NULL,
   label_id INTEGER NOT NULL,
   PRIMARY KEY(project_version_id, label_id),
   FOREIGN KEY (project_version_id) REFERENCES project_version (project_version_id) ON DELETE CASCADE,
   FOREIGN KEY (label_id) REFERENCES label (label_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS heuristic (
   heuristic_id INTEGER PRIMARY KEY AUTOINCREMENT,
   pattern TEXT,
   label_id INTEGER,
   FOREIGN KEY (label_id) REFERENCES label (label_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS execution (
   execution_id INTEGER PRIMARY KEY AUTOINCREMENT,
   output TEXT,
   validated BOOLEAN,
   accepted BOOLEAN,
   heuristic_id INTEGER,
   project_version_id INTEGER,
   FOREIGN KEY (heuristic_id) REFERENCES heuristic (heuristic_id) ON DELETE CASCADE,
   FOREIGN KEY (project_version_id) REFERENCES project_version (project_version_id) ON DELETE CASCADE
);