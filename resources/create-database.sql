CREATE DATABASE db-mining;

CREATE TABLE project (
   project_id INTEGER PRIMARY KEY AUTOINCREMENT,
   owner TEXT,
   name TEXT,
   language TEXT, 
   domain TEXT
); 

CREATE TABLE project_version (
   version_id INTEGER PRIMARY KEY AUTOINCREMENT, 
   version TEXT, 
   last BOOLEAN,
   project_id INTEGER,
   FOREIGN KEY (project_id) REFERENCES project (project_id) ON DELETE RESTRICT
);

CREATE TABLE database_type (
   type_id INTEGER PRIMARY KEY AUTOINCREMENT, 
   name TEXT
);


CREATE TABLE database (
   database_id INTEGER PRIMARY KEY AUTOINCREMENT,
   name TEXT, 
   type_id INTEGER,
   FOREIGN KEY (type_id) REFERENCES database_type (type_id) ON DELETE RESTRICT 
);

CREATE TABLE project_database (
   project_id INTEGER NOT NULL, 
   database_id INTEGER NOT NULL,
   PRIMARY KEY (project_id, database_id),
   FOREIGN KEY (project_id) REFERENCES project (project_id) ON DELETE RESTRICT,
   FOREIGN KEY (database_id) REFERENCES database (database_id) ON DELETE RESTRICT
);

CREATE TABLE strategy (
   strategy_id INTEGER PRIMARY KEY AUTOINCREMENT, 
   type TEXT,
   name TEXT
); 

CREATE TABLE project_strategy (
   project_id INTEGER NOT NULL, 
   strategy_id INTEGER NOT NULL, 
   PRIMARY KEY (project_id, strategy_id),
   FOREIGN KEY (project_id) REFERENCES project (project_id) ON DELETE RESTRICT,
   FOREIGN KEY (strategy_id) REFERENCES strategy (strategy_id) ON DELETE RESTRICT
);   
   

   
