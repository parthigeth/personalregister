from flask import Flask, render_template, request, jsonify, send_file
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import pandas as pd
import sqlite3
import logging
import io
import os

app = Flask(__name__)

# Set up logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(levelname)s: %(message)s',
                   filename='file_summary_log.txt')

# Database initialization
def init_db():
    conn = sqlite3.connect('file_data.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS files 
                 (file_number TEXT PRIMARY KEY,
                  received_month INTEGER,
                  received_year INTEGER,
                  status TEXT,
                  closed_month INTEGER, 
                  closed_year INTEGER)''')
    conn.commit()
    conn.close()

init_db()

# Month mappings and utilities
month_mapping = {
    'January': 1, 'February': 2, 'March': 3, 'April': 4, 'May': 5, 'June': 6,
    'July': 7, 'August': 8, 'September': 9, 'October': 10, 'November': 11, 'December': 12
}

def get_short_month(month_name):
    month_shorts = {
        'January': 'Jan', 'February': 'Feb', 'March': 'Mar', 'April': 'Apr',
        'May': 'May', 'June': 'Jun', 'July': 'Jul', 'August': 'Aug',
        'September': 'Sep', 'October': 'Oct', 'November': 'Nov', 'December': 'Dec'
    }
    return month_shorts.get(month_name, month_name)

def month_name_to_number(month_name):
    return month_mapping.get(month_name, None)

def number_to_month_name(month_number):
    month_mapping_inv = {v: k for k, v in month_mapping.items()}
    return month_mapping_inv.get(month_number, None)

def apply_excel_formatting(writer, worksheet):
    workbook = writer.book
    border_fmt = workbook.add_format({
        'border': 1,
        'align': 'center',
        'valign': 'vcenter'
    })
    header_fmt = workbook.add_format({
        'border': 1,
        'bold': True,
        'align': 'center',
        'valign': 'vcenter',
        'bg_color': '#D3D3D3'
    })

    max_row = worksheet.dim_rowmax
    max_col = worksheet.dim_colmax

    worksheet.set_row(0, None, header_fmt)
    
    for row in range(1, max_row + 1):
        worksheet.set_row(row, None, border_fmt)
    
    for col in range(max_col + 1):
        worksheet.set_column(col, col, None, border_fmt)

# Original summary generation functions
def get_pending_up_to_previous_month(data, selected_month, selected_year):
    prev_month = selected_month - 1 if selected_month > 1 else 12
    prev_year = selected_year if selected_month > 1 else selected_year - 1
    prev_month_end = datetime(prev_year, prev_month, 1) + relativedelta(day=31)

    qualified_files = data[
        (data['Received Date'] <= prev_month_end) &
        ((data['Status'] == 'Pending') |
         ((data['Status'] == 'Closed') &
          (data['Closed Month'].apply(lambda x: month_mapping[x] if pd.notna(x) and x in month_mapping else 0) == selected_month) &
          (data['Closed Year'] == selected_year)) |
         ((data['Status'] == 'Closed') &
          ((data['Closed Year'] > selected_year) |
           ((data['Closed Year'] == selected_year) &
            (data['Closed Month'].apply(
                lambda x: month_mapping[x] if pd.notna(x) and x in month_mapping else 0) > selected_month)))))
        ]

    return qualified_files

def generate_monthly_summary_df(selected_month, selected_year):
    prev_month = selected_month - 1 if selected_month > 1 else 12
    prev_year = selected_year if selected_month > 1 else selected_year - 1

    current_month_start = datetime(selected_year, selected_month, 1)
    current_month_end = current_month_start.replace(day=28) + timedelta(days=4)
    current_month_end = current_month_end - timedelta(days=current_month_end.day)
    prev_month_end = current_month_start - timedelta(days=1)

    three_months_ago_start = current_month_start - relativedelta(months=2)
    six_months_ago_start = current_month_start - relativedelta(months=5)
    one_year_ago_start = current_month_start - relativedelta(months=11)

    conn = sqlite3.connect('file_data.db')
    c = conn.cursor()
    c.execute("SELECT * FROM files")
    files = c.fetchall()
    data = pd.DataFrame(files, columns=['File Number', 'Received Month', 'Received Year', 'Status',
                                      'Closed Month', 'Closed Year'])
    conn.close()

    # Convert month numbers to names
    data['Received Month'] = data['Received Month'].apply(lambda x: number_to_month_name(x) if pd.notna(x) else x)
    data['Closed Month'] = data['Closed Month'].apply(lambda x: number_to_month_name(x) if pd.notna(x) else x)

    data['Received Date'] = pd.to_datetime(
        data['Received Year'].astype(str) + '-' +
        data['Received Month'].apply(lambda x: str(month_mapping[x] if pd.notna(x) and x in month_mapping else 1)),
        format='%Y-%m', errors='coerce')

    data['Closed Date'] = pd.to_datetime(
        data['Closed Year'].astype(str) + '-' +
        data['Closed Month'].apply(lambda x: str(month_mapping[x] if pd.notna(x) and x in month_mapping else 1)),
        format='%Y-%m', errors='coerce')

    # Calculate different categories of files
    pending_within_3_months = data[
        (data['Received Date'] >= three_months_ago_start) &
        (data['Received Date'] < current_month_end) &
        ((data['Status'] == 'Pending') |
         ((data['Status'] == 'Closed') &
          ((data['Closed Year'] > selected_year) |
           ((data['Closed Year'] == selected_year) &
            (data['Closed Month'].apply(lambda x: month_mapping[x] if pd.notna(x) and x in month_mapping else 0) > selected_month)) |
           ((data['Closed Year'] < selected_year) &
            (data['Closed Month'].apply(lambda x: month_mapping[x] if pd.notna(x) and x in month_mapping else 0) < selected_month - 1)))))
        ]

    pending_above_3_months = data[
        (data['Received Date'] >= six_months_ago_start) &
        (data['Received Date'] < three_months_ago_start) &
        ((data['Status'] == 'Pending') |
         ((data['Status'] == 'Closed') &
          ((data['Closed Year'] > selected_year) |
           ((data['Closed Year'] == selected_year) &
            (data['Closed Month'].apply(lambda x: month_mapping[x] if pd.notna(x) and x in month_mapping else 0) > selected_month)) |
           ((data['Closed Year'] < selected_year) &
            (data['Closed Month'].apply(lambda x: month_mapping[x] if pd.notna(x) and x in month_mapping else 0) < selected_month - 1)))))
        ]

    pending_above_6_months = data[
        (data['Received Date'] >= one_year_ago_start) &
        (data['Received Date'] < six_months_ago_start) &
        ((data['Status'] == 'Pending') |
         ((data['Status'] == 'Closed') &
          ((data['Closed Year'] > selected_year) |
           ((data['Closed Year'] == selected_year) &
            (data['Closed Month'].apply(lambda x: month_mapping[x] if pd.notna(x) and x in month_mapping else 0) > selected_month)) |
           ((data['Closed Year'] < selected_year) &
            (data['Closed Month'].apply(lambda x: month_mapping[x] if pd.notna(x) and x in month_mapping else 0) < selected_month - 1)))))
        ]

    pending_above_one_year = data[
        (data['Received Date'] < one_year_ago_start) &
        ((data['Status'] == 'Pending') |
         ((data['Status'] == 'Closed') &
          ((data['Closed Year'] > selected_year) |
           ((data['Closed Year'] == selected_year) &
            (data['Closed Month'].apply(lambda x: month_mapping[x] if pd.notna(x) and x in month_mapping else 0) > selected_month)) |
           ((data['Closed Year'] < selected_year) &
            (data['Closed Month'].apply(lambda x: month_mapping[x] if pd.notna(x) and x in month_mapping else 0) < selected_month - 1)))))
        ]

    pending_upto_previous_month = get_pending_up_to_previous_month(data, selected_month, selected_year)
    new_files_current_month = data[
        (data['Received Date'] >= current_month_start) &
        (data['Received Date'] <= current_month_end) &
        (data['Status'].isin(['Pending', 'Closed']))
        ]
    total_files_for_month = len(pending_upto_previous_month) + len(new_files_current_month)
    closed_current_month = data[
        (data['Status'] == 'Closed') &
        (data['Closed Month'].apply(lambda x: month_mapping[x] if pd.notna(x) and x in month_mapping else 0) == selected_month) &
        (data['Closed Year'] == selected_year)
        ]

    total_pending = (len(pending_within_3_months) + len(pending_above_3_months) +
                    len(pending_above_6_months) + len(pending_above_one_year))
    pending_percentage = (total_pending / total_files_for_month * 100) if total_files_for_month > 0 else 0

    categories = [
        f'Pending Files Up to {prev_month_end.strftime("%B %Y")}',
        f'New Files Received in {current_month_start.strftime("%B %Y")}',
        f'Total Files Available for {current_month_start.strftime("%B %Y")} Activities',
        f'Closed Files in {current_month_start.strftime("%B %Y")}',
        'Pending Files Within 3 Months',
        'Pending Files Above 3 Months',
        'Pending Files Above 6 Months',
        'Pending Files Above One Year',
        'Total Pending (S.No 5 + S.No 6 + S.No 7 + S.No 8)',
        'Pending Percentage (S.No 9 / S.No 3) * 100'
    ]

    file_numbers = [
        len(pending_upto_previous_month),
        len(new_files_current_month),
        total_files_for_month,
        len(closed_current_month),
        len(pending_within_3_months),
        len(pending_above_3_months),
        len(pending_above_6_months),
        len(pending_above_one_year),
        total_pending,
        round(pending_percentage, 2)
    ]

    summary_data = {
        'S.No': list(range(1, len(categories) + 1)),
        'Summary Category': categories,
        'Number Of Files': file_numbers
    }

    df_dict = {
        1: pending_upto_previous_month,
        2: new_files_current_month,
        3: pd.concat([pending_upto_previous_month, new_files_current_month]),
        4: closed_current_month,
        5: pending_within_3_months,
        6: pending_above_3_months,
        7: pending_above_6_months,
        8: pending_above_one_year,
        9: pd.concat([pending_within_3_months, pending_above_3_months,
                     pending_above_6_months, pending_above_one_year])
    }

    return pd.DataFrame(summary_data), df_dict, current_month_start


# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/files', methods=['GET'])
def get_files():
    conn = sqlite3.connect('file_data.db')
    c = conn.cursor()
    c.execute("SELECT * FROM files")
    files = c.fetchall()
    conn.close()

    file_list = []
    for file in files:
        file_dict = {
            'file_number': file[0],
            'received_month': number_to_month_name(file[1]),
            'received_year': file[2],
            'status': file[3],
            'closed_month': number_to_month_name(file[4]) if file[4] else None,
            'closed_year': file[5]
        }
        file_list.append(file_dict)
    
    return jsonify(file_list)

@app.route('/api/files', methods=['POST'])
def add_file():
    data = request.json
    conn = sqlite3.connect('file_data.db')
    c = conn.cursor()
    
    try:
        received_month = month_name_to_number(data['received_month'])
        closed_month = month_name_to_number(data['closed_month']) if data['status'] == 'Closed' else None
        closed_year = data['closed_year'] if data['status'] == 'Closed' else None

        c.execute('''INSERT INTO files VALUES (?, ?, ?, ?, ?, ?)''',
                 (data['file_number'], received_month, data['received_year'],
                  data['status'], closed_month, closed_year))
        
        conn.commit()
        conn.close()
        return jsonify({'status': 'success'})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'status': 'error', 'message': 'Duplicate file number'}), 400
    except Exception as e:
        conn.close()
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/files/<file_number>', methods=['PUT'])
def update_file(file_number):
    data = request.json
    conn = sqlite3.connect('file_data.db')
    c = conn.cursor()
    
    try:
        received_month = month_name_to_number(data['received_month'])
        closed_month = month_name_to_number(data['closed_month']) if data['status'] == 'Closed' else None
        closed_year = data['closed_year'] if data['status'] == 'Closed' else None

        c.execute('''UPDATE files 
                    SET received_month=?, received_year=?, status=?, 
                        closed_month=?, closed_year=?
                    WHERE file_number=?''',
                 (received_month, data['received_year'], data['status'],
                  closed_month, closed_year, file_number))
        
        conn.commit()
        conn.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        conn.close()
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/files/<file_number>', methods=['DELETE'])
def delete_file(file_number):
    conn = sqlite3.connect('file_data.db')
    c = conn.cursor()
    try:
        c.execute("DELETE FROM files WHERE file_number=?", (file_number,))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        conn.close()
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/summary/monthly', methods=['GET'])
def generate_monthly_file_summary():
    selected_month = int(request.args.get('month'))
    selected_year = int(request.args.get('year'))

    summary_df, _, _ = generate_monthly_summary_df(selected_month, selected_year)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        summary_df.to_excel(writer, sheet_name='Summary', index=False)
        worksheet = writer.sheets['Summary']
        apply_excel_formatting(writer, worksheet)
        worksheet.set_column('A:A', 8)
        worksheet.set_column('B:B', 40)
        worksheet.set_column('C:C', 15)

    output.seek(0)
    logging.info(f"Monthly summary generated for {selected_month}/{selected_year}")
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'monthly_summary_{selected_year}_{selected_month}.xlsx'
    )

@app.route('/api/summary/detailed', methods=['GET'])
def generate_detailed_summary():
    selected_month = int(request.args.get('month'))
    selected_year = int(request.args.get('year'))

    summary_df, df_dict, _ = generate_monthly_summary_df(selected_month, selected_year)
    detailed_df = pd.DataFrame()

    for idx, row in summary_df.iterrows():
        category_dict = {
            'S.No': row['S.No'],
            'Summary Category': row['Summary Category'],
            'Number Of Files': row['Number Of Files'],
            'File List': ', '.join(df_dict[row['S.No']]['File Number'].tolist()) if row['S.No'] < 10 else 'N/A'
        }
        detailed_df = pd.concat([detailed_df, pd.DataFrame([category_dict])], ignore_index=True)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        detailed_df.to_excel(writer, sheet_name='Detailed Summary', index=False)
        worksheet = writer.sheets['Detailed Summary']
        apply_excel_formatting(writer, worksheet)
        worksheet.set_column('A:A', 8)
        worksheet.set_column('B:B', 40)
        worksheet.set_column('C:C', 15)
        worksheet.set_column('D:D', 100)

    output.seek(0)
    logging.info(f"Detailed summary generated for {selected_month}/{selected_year}")
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'detailed_summary_{selected_year}_{selected_month}.xlsx'
    )

@app.route('/api/filter', methods=['GET'])
def filter_files():
    selected_month = int(request.args.get('month'))
    selected_year = int(request.args.get('year'))
    
    conn = sqlite3.connect('file_data.db')
    c = conn.cursor()
    c.execute("SELECT * FROM files WHERE received_month=? AND received_year=?", 
             (selected_month, selected_year))
    files = c.fetchall()
    conn.close()
    
    file_list = []
    for file in files:
        file_dict = {
            'file_number': file[0],
            'received_month': number_to_month_name(file[1]),
            'received_year': file[2],
            'status': file[3],
            'closed_month': number_to_month_name(file[4]) if file[4] else None,
            'closed_year': file[5]
        }
        file_list.append(file_dict)
    
    return jsonify(file_list)

@app.route('/api/stats', methods=['GET'])
def get_stats():
    selected_month = int(request.args.get('month'))
    selected_year = int(request.args.get('year'))
    
    summary_df, df_dict, _ = generate_monthly_summary_df(selected_month, selected_year)
    
    stats = {}
    for _, row in summary_df.iterrows():
        stats[f"category_{row['S.No']}"] = {
            'label': row['Summary Category'],
            'value': row['Number Of Files'],
            'files': df_dict[row['S.No']]['File Number'].tolist() if row['S.No'] in df_dict else []
        }
    
    return jsonify(stats)

@app.route('/api/export', methods=['GET'])
def export_all_files():
    conn = sqlite3.connect('file_data.db')
    df = pd.read_sql_query("SELECT * FROM files", conn)
    conn.close()
    
    # Convert month numbers to names
    df['received_month'] = df['received_month'].apply(number_to_month_name)
    df['closed_month'] = df['closed_month'].apply(lambda x: number_to_month_name(x) if pd.notna(x) else None)
    
    # Reorder columns
    df = df[['file_number', 'received_month', 'received_year', 'status', 'closed_month', 'closed_year']]
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Files', index=False)
        worksheet = writer.sheets['Files']
        apply_excel_formatting(writer, worksheet)
        worksheet.set_column('A:A', 15)  # File Number
        worksheet.set_column('B:B', 15)  # Received Month
        worksheet.set_column('C:C', 12)  # Received Year
        worksheet.set_column('D:D', 10)  # Status
        worksheet.set_column('E:E', 15)  # Closed Month
        worksheet.set_column('F:F', 12)  # Closed Year

    output.seek(0)
    logging.info("Full file export generated")
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='file_export.xlsx'
    )

@app.route('/api/pending', methods=['GET'])
def get_pending_files():
    conn = sqlite3.connect('file_data.db')
    c = conn.cursor()
    c.execute("SELECT * FROM files WHERE status='Pending'")
    files = c.fetchall()
    conn.close()
    
    file_list = []
    for file in files:
        file_dict = {
            'file_number': file[0],
            'received_month': number_to_month_name(file[1]),
            'received_year': file[2],
            'status': file[3],
            'closed_month': number_to_month_name(file[4]) if file[4] else None,
            'closed_year': file[5]
        }
        file_list.append(file_dict)
    
    return jsonify(file_list)

if __name__ == '__main__':
    app.run(debug=True)


