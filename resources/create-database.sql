CREATE TABLE IF NOT EXISTS language (
   language_id INTEGER PRIMARY KEY AUTOINCREMENT,
   name TEXT
);

CREATE TABLE IF NOT EXISTS domain (
   domain_id INTEGER PRIMARY KEY AUTOINCREMENT,
   name TEXT
);

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
   language_id INTEGER,
   domain_id INTEGER,
   FOREIGN KEY (language_id) REFERENCES language (language_id) ON DELETE RESTRICT,
   FOREIGN KEY (domain_id) REFERENCES domain (domain_id) ON DELETE RESTRICT
);


CREATE TABLE IF NOT EXISTS project_version (
   project_version_id INTEGER PRIMARY KEY AUTOINCREMENT,
   sha1 TEXT,
   last BOOLEAN,
   project_id INTEGER,
   FOREIGN KEY (project_id) REFERENCES project (project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS database_type (
   type_id INTEGER PRIMARY KEY AUTOINCREMENT, 
   name TEXT
);

CREATE TABLE IF NOT EXISTS database (
   database_id INTEGER PRIMARY KEY AUTOINCREMENT,
   name TEXT, 
   type_id INTEGER,
   FOREIGN KEY (type_id) REFERENCES database_type (type_id) ON DELETE RESTRICT 
);

CREATE TABLE IF NOT EXISTS query_strategy (
   query_strategy_id INTEGER PRIMARY KEY AUTOINCREMENT,
   name TEXT
);

CREATE TABLE IF NOT EXISTS implementation_strategy (
   implementation_strategy_id INTEGER PRIMARY KEY AUTOINCREMENT,
   name TEXT
);

CREATE TABLE IF NOT EXISTS heuristic (
   heuristic_id INTEGER PRIMARY KEY AUTOINCREMENT,
   regex TEXT,
   type TEXT,
   database_id INTEGER,
   language_id INTEGER,
   query_strategy_id INTEGER,
   implementation_strategy_id INTEGER,
   FOREIGN KEY (database_id) REFERENCES database (database_id) ON DELETE CASCADE,
   FOREIGN KEY (language_id) REFERENCES language (language_id) ON DELETE CASCADE,
   FOREIGN KEY (query_strategy_id) REFERENCES query_strategy (query_strategy_id) ON DELETE CASCADE,
   FOREIGN KEY (implementation_strategy_id) REFERENCES implementation_strategy (implementation_strategy_id) ON DELETE CASCADE
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