CREATE TABLE IF NOT EXISTS project (
   id INTEGER PRIMARY KEY AUTOINCREMENT,
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

CREATE TABLE IF NOT EXISTS version (
   id INTEGER PRIMARY KEY AUTOINCREMENT,
   sha1 TEXT,
   isLast BOOLEAN,
   project_id INTEGER,
   FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS category (
   id INTEGER PRIMARY KEY AUTOINCREMENT,
   name TEXT
);

CREATE TABLE IF NOT EXISTS label (
   id INTEGER PRIMARY KEY AUTOINCREMENT,
   name TEXT,
   type TEXT
);

CREATE TABLE IF NOT EXISTS label_category (
   label_id INTEGER NOT NULL,
   category_id INTEGER NOT NULL,
   isMain BOOLEAN,
   PRIMARY KEY (label_id, category_id),
   FOREIGN KEY (label_id) REFERENCES label(id) ON DELETE CASCADE,
   FOREIGN KEY (category_id) REFERENCES category(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS version_label (
   version_id INTEGER NOT NULL,
   label_id INTEGER NOT NULL,
   PRIMARY KEY(version_id, label_id),
   FOREIGN KEY (version_id) REFERENCES version(id) ON DELETE CASCADE,
   FOREIGN KEY (label_id) REFERENCES label(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS heuristic (
   id INTEGER PRIMARY KEY AUTOINCREMENT,
   pattern TEXT,
   label_id INTEGER,
   FOREIGN KEY (label_id) REFERENCES label(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS execution (
   id INTEGER PRIMARY KEY AUTOINCREMENT,
   output TEXT,
   isValidated BOOLEAN,
   isAccepted BOOLEAN,
   heuristic_id INTEGER,
   version_id INTEGER,
   FOREIGN KEY (heuristic_id) REFERENCES heuristic(id) ON DELETE CASCADE,
   FOREIGN KEY (version_id) REFERENCES version(id) ON DELETE CASCADE
);