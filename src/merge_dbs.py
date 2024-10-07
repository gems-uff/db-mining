import argparse
import shutil
import sqlite3


def mergedbs(first, second, output, dryrun):
    con2 = sqlite3.connect(second)
    if not dryrun:
        shutil.copyfile(first, output)
        con1 = sqlite3.connect(output)
    else:
        con1 = sqlite3.connect(first)
    
    label_map = migrate_seq_id(
        con1, con2, "label", ["name", "type"], dryrun=dryrun)
    heuristic_map = migrate_seq_id(
        con1, con2, "heuristic", ["label_id", "pattern"], {'label_id': label_map}, dryrun=dryrun)
    category_map = migrate_seq_id(
        con1, con2, "category", ["name"], dryrun=dryrun)
    migrate_composed_id(
        con1, con2, "label_category", ["label_id", "category_id"],
        {"label_id": label_map, "category_id": category_map}, dryrun=dryrun)
    migrate_seq_id(
        con1, con2, "vulnerability", ["label_id", "name"], {"label_id": label_map}, create_map=False, dryrun=dryrun)
    del label_map
    del category_map
    project_map = migrate_seq_id(
        con1, con2, "project", ["owner", "name"], dryrun=dryrun)
    version_map = migrate_seq_id(
        con1, con2, "version", ["project_id", "sha1"], {'project_id': project_map}, dryrun=dryrun)
    del project_map
    migrate_seq_id(
        con1, con2, "execution", ["heuristic_id", "version_id"],
        {'heuristic_id': heuristic_map, 'version_id': version_map}, create_map=False, dryrun=dryrun)
    


def read_description(cursor, info_fields, map_fields, id_field="id"):
    id_pos = None
    info_pos = []
    map_fields_pos = {}
    order = []
    for pos, value in enumerate(cursor.description):
        order.append(value[0])
        if value[0] == id_field:
            id_pos = pos
        if value[0] in info_fields:
            info_pos.append(pos)
        if value[0] in map_fields:
            map_fields_pos[pos] = map_fields[value[0]]
    return id_pos, order, info_pos, map_fields_pos


def insert_rows(con1, table, order1, new_rows, dryrun):
    print(f"> Inserting {len(new_rows)} rows into {table}")
    con1.executemany(f"INSERT INTO {table} ({', '.join(order1)}) VALUES ({', '.join('?' * len(order1))})", new_rows)
    if not dryrun:
        con1.commit()

def migrate_seq_id(con1, con2, table, info_fields, map_fields=None, id_field="id", dryrun=False, create_map=True):
    cursor1 = con1.cursor()
    cursor2 = con2.cursor()
    print(f"Processing table {table}")
    if map_fields is None:
        map_fields = {}
    query = cursor1.execute(f'SELECT * FROM {table}')
    id_pos, order1, info_pos, map_fields_pos = read_description(cursor1, info_fields, map_fields, id_field)
    last_id = 0
    info_map = {}
    for row in query:
        last_id = max(row[id_pos], last_id)
        info_map[tuple(row[index] for index in info_pos)] = row[id_pos]

    found = 0
    result_map = {}
    new_rows = []
    query = cursor2.execute(f'SELECT * FROM {table}')
    id_pos, order2, info_pos, map_fields_pos = read_description(cursor2, info_fields, map_fields, id_field)
    reorder = order1 != order2
    for row in query:
        row = list(row)
        for key_id, field_map in map_fields_pos.items():
            row[key_id] = field_map[row[key_id]]
        info_tuple = tuple(row[index] for index in info_pos)
        if info_tuple in info_map:
            if create_map:
                result_map[row[id_pos]] = info_map[info_tuple]
            found += 1
        else:
            last_id += 1
            if create_map:
                result_map[row[id_pos]] = last_id
            row[id_pos] = last_id
            if reorder:
                row = [row[order2.index(key)] for key in order1]
            new_rows.append(tuple(row))
            if len(new_rows) % 5000 == 0:
                insert_rows(con1, table, order1, new_rows, dryrun)
                new_rows = []
    
    if new_rows and not dryrun:
        insert_rows(con1, table, order1, new_rows, dryrun)
    print(f"> Found {found} equivalent rows.")
    return result_map


def migrate_composed_id(con1, con2, table, info_fields, map_fields=None, dryrun=False):
    cursor1 = con1.cursor()
    cursor2 = con2.cursor()
    print(f"Processing table {table}")
    if map_fields is None:
        map_fields = {}
    query = cursor1.execute(f'SELECT * FROM {table}')
    _, order1, info_pos, map_fields_pos = read_description(cursor1, info_fields, map_fields)

    info_map = set()
    for row in query:
        info_map.add(tuple(row[index] for index in info_pos))

    found = 0
    result_map = {}
    new_rows = []
    query = cursor2.execute(f'SELECT * FROM {table}')
    _, order2, info_pos, map_fields_pos = read_description(cursor2, info_fields, map_fields)
    reorder = order1 != order2
    for row in query:
        row = list(row)
        for key_id, field_map in map_fields_pos.items():
            row[key_id] = field_map[row[key_id]]
        
        info_tuple = tuple(row[index] for index in info_pos)
        if info_tuple in info_map:
            found += 1
        else:
            last_id += 1
            if reorder:
                row = [row[order2.index(key)] for key in order1]
            new_rows.append(tuple(row))
            if len(new_rows) % 5000 == 0:
                insert_rows(con1, table, order1, new_rows, dryrun)
                new_rows = []
    
    if new_rows and not dryrun:
        insert_rows(con1, table, order1, new_rows, dryrun)
    print(f"> Found {found} equivalent rows.")


def main():
    parser = argparse.ArgumentParser(
        prog='mergedbs',
        description='Merge sqlite databases')

    parser.add_argument(
        'first',
        help="First sqlite file")
    parser.add_argument(
        'second',
        help="Second sqlite file")
    parser.add_argument(
        'output',
        help="Output sqlite file")
    parser.add_argument(
        '--dry-run', action="store_true",
        help="Do not insert merged data into database"
    )
    args = parser.parse_args()

    mergedbs(args.first, args.second, args.output, args.dry_run)


if __name__ == '__main__':
    main()
