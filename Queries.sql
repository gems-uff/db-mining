select execution.id, execution.output, execution.heuristic_id, execution.version_id,
p.owner, p.name, v.isLast
from main.execution
join version v on execution.version_id = v.id
join project p on v.project_id = p.id
where output like '%<artifactId>jtds%' and heuristic_id in (3, 42);


select execution.id, execution.output, execution.heuristic_id, execution.version_id,
p.owner, p.name, v.isLast
from main.execution
join version v on execution.version_id = v.id
join project p on v.project_id = p.id
where output is not '' and heuristic_id in (3) and v.isLast is TRUE;

select execution.id, execution.output, execution.heuristic_id, execution.version_id, v.date_commit,
p.owner, p.name, v.isLast
from main.execution
join version v on execution.version_id = v.id
join project p on v.project_id = p.id
where output like '%jdbc:sybase%' and heuristic_id in (3, 42);


--like '%<artifactId>jtds%'

select execution.id, execution.output, execution.heuristic_id, execution.version_id,
p.owner, p.name, v.isLast
from main.execution
join version v on execution.version_id = v.id
join project p on v.project_id = p.id
where output is not '' and heuristic_id in (42, 3) and v.isLast is TRUE;


select distinct  p.owner, p.name
--execution.id, execution.output, execution.heuristic_id, execution.version_id, p.owner, p.name, v.isLast
from main.execution
join version v on execution.version_id = v.id
join project p on v.project_id = p.id
where output is not '' and heuristic_id in (42, 3);

select * 
from heuristic 
join label on label.id = heuristic.label_id
where name like "H2";

select * 
from version_vulnerability
join execution on version_vulnerability.execution_id = execution.id 
where execution.heuristic_id = 1 ;

SELECT DISTINCT version_vulnerability.versionNumber
FROM version_vulnerability
JOIN execution ON version_vulnerability.execution_id = execution.id
WHERE execution.heuristic_id = 1
  AND version_vulnerability.versionNumber IS NOT NULL
  AND TRIM(version_vulnerability.versionNumber) <> '';


  SELECT DISTINCT ON (version_vulnerability.versionNumber) version_vulnerability.*
FROM version_vulnerability
JOIN execution ON version_vulnerability.execution_id = execution.id
WHERE execution.heuristic_id = 1
  AND version_vulnerability.versionNumber IS NOT NULL
  AND TRIM(version_vulnerability.versionNumber) <> '';


SELECT vv.*
FROM version_vulnerability vv
JOIN execution e ON vv.execution_id = e.id
JOIN (
    SELECT MIN(id) AS id
    FROM version_vulnerability
    WHERE versionNumber IS NOT NULL AND TRIM(versionNumber) <> ''
    GROUP BY versionNumber
) AS uniq ON vv.id = uniq.id
WHERE e.heuristic_id = 1;


SELECT *
FROM version_vulnerability vv
JOIN execution e ON vv.execution_id = e.id
WHERE e.heuristic_id = 1
  AND vv.versionNumber IN (
    SELECT DISTINCT versionNumber
    FROM version_vulnerability
    WHERE versionNumber IS NOT NULL AND TRIM(versionNumber) <> ''
  );


select * from vulnerability
where label_id = 3 and reference = 'CVE-123-2344';

select * from version_vulnerability where file like '%qa/%';


-- "Liste todas as vulnerabilidades detectadas, mostrando qual versão e commit do projeto, 
-- qual heurística as identificou, e em que arquivo/versionNumber foram encontradas — 
-- ordenando da mais recente para a mais antiga.”

SELECT version_vulnerability.versionNumber, version_vulnerability.file, version_vulnerability.version_id, 
version.date_commit, version.sha1, heuristic.pattern, version_vulnerability.execution_id
FROM version_vulnerability
JOIN version ON version_vulnerability.version_id = version.id
JOIN execution ON version_vulnerability.execution_id = execution.id
JOIN heuristic on execution.heuristic_id = heuristic.id 
ORDER BY version.date_commit DESC;

WHERE version.project_id = 3 and heuristic.id = 29;

version_vulnerability.versionNumber <> 'undefined' and version_vulnerability.versionNumber not like '%$%';

WHERE version_vulnerability.versionNumber like '$';

SELECT count(*) 
FROM version_vulnerability
JOIN version ON version_vulnerability.version_id = version.id
JOIN execution ON version_vulnerability.execution_id = execution.id
JOIN heuristic on execution.heuristic_id = heuristic.id
WHERE version_vulnerability.versionNumber <> 'undefined' and version_vulnerability.versionNumber not like '%$%';
WHERE version_vulnerability.versionNumber like '%$%';
WHERE version_vulnerability.versionNumber like 'undefined';

--undefined: tag vazia ou inexistente

WHERE version_vulnerability.file LIKE '%/Users/camilapaiva/Documents/GitHub/repos/naver/pinpoint/agent-module/agent-testweb/mongodb-plugin-testweb/pom.xml%';

Total de registros: 1005
Total pom.xml 710
Total outros arquivos 295
.txt
.adoc
.properties
.java
.md

version.project_id = 1 AND execution.heuristic_id = 1 and version_vulnerability.versionNumber = '1.2.132'  and 

 and heuristic_id= 1;


update execution
set output = ''
where execution.id in (863295,
1195575,
1196771,
1199631,
1212631);

--output like '%<artifactId>jtds%' and

Análises para o arquivo pom.xml

heuristica para o postgressql parece estar faltando exemplos. peguei uns dados para análise que falta a heuristica: <artifact>postgresql
ID: 22

heuristic 346, não conseguiu extrair a versão do pom.xml corretamente. 

heuristic 347, uso de oracle ojdbc, não pegou na heuristica. não extratiu a versão

não capturou o Jedis, 348. acho que a busca da heuristica na linha não está correta. 

não extraiu a versão para: <artifactId>[1;31mmysql-connector-java[m</artifactId>
nem para: [36m:[m        <artifactId>[1;31mojdbc[m5</artifactId>
nem para: [1;31m<artifactId>postgresql[m</artifactId>


Levar para a reunião: 
1 - Mudança na estrutura, buscar no banco e salvar se não tiver a mesma versão, banco e arquivo
2 - Buscar a linha que tem a heuristica detectada e só após buscar a versão, evitar pegar a versão errada
3 - Existem outros arquivos sem ser do tipo pom.xml retornados, desconsiderar? 
4 - Trazer a ideia de buscar o gitlog no gradle e comparar os commits. assim nossa lista já vem atualizada
5 - Para buscar a versão do gradle, achando o BD, logo depois dos dois pontos está disponível


SELECT
  vv.versionNumber,
  h.pattern,
  l.name ,
  vv.file,
  vv.version_id,
  p.name,
  v.date_commit,
  v.project_id,
  vv.execution_id
FROM version_vulnerability AS vv
JOIN version   AS v ON vv.version_id = v.id
JOIN project AS p on v.project_id = p.id
JOIN execution AS e ON vv.execution_id = e.id
JOIN heuristic AS h ON e.heuristic_id = h.id
JOIN label AS l ON h.label_id = l.id ;
and l.name like "%Activ%" ;
ORDER BY h.pattern ASC, v.date_commit ASC;

SELECT
  vv.versionNumber,
  h.pattern,
  l.name ,
  vv.file,
  vv.version_id,
  p.name as project_name,
  v.date_commit,
  v.sha1,
  v.project_id,
  vv.execution_id
FROM version_vulnerability AS vv
JOIN version   AS v ON vv.version_id = v.id
JOIN project AS p on v.project_id = p.id
JOIN execution AS e ON vv.execution_id = e.id
JOIN heuristic AS h ON e.heuristic_id = h.id
JOIN label AS l ON h.label_id = l.id ;